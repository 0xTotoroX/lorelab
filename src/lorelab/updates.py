"""[INPUT]: 明确指定的本地包或 HTTPS 更新清单、受管 prefix。
[OUTPUT]: 校验过的缓存包及整套升级结果，复用安装器的原子切换。
[POS]: 更新传输与候选校验；不修改用户配置、任务或远端服务。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import contextlib
import hashlib
import json
import os
import re
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

from . import maintenance

MAX_BYTES = 2 * 1024**3


def validate_location(value: str) -> str:
    if "://" not in value:
        return str(Path(value).expanduser().resolve())
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("远程更新地址必须是无内嵌账号密码的 HTTPS URL。")
    return value


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_location(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def remote_open(url):
    try:
        return urllib.request.build_opener(HTTPSRedirect()).open(url, timeout=30)
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("更新下载失败；当前安装不变，请检查网络和更新地址。") from exc


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url: str, expected: str, directory: Path) -> tuple[Path, bool]:
    validate_location(url)
    if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
        raise ValueError("远程安装包需要有效的 --sha256 或更新清单 SHA256。")
    expected = expected.lower()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f"{expected}.tar.gz"
    if target.is_symlink():
        raise ValueError("更新缓存不能是符号链接。")
    if target.is_file() and sha256(target) == expected:
        return target, True
    pending = directory / f".{expected}-{uuid.uuid4().hex}.part"
    try:
        digest, size = hashlib.sha256(), 0
        with remote_open(url) as response, pending.open("xb") as output:
            pending.chmod(0o600)
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("安装包超过允许的大小。")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("安装包 SHA256 不匹配；没有安装。")
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)
    return target, False


def read_feed(location: str) -> dict:
    location = validate_location(location)
    if location.startswith("https://"):
        with remote_open(location) as response:
            data = response.read(1024 * 1024 + 1)
    else:
        with Path(location).open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("更新清单过大。")
    value = json.loads(data)
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("product") != "lorelab" or not isinstance(value.get("url"), str)):
        raise ValueError("无效的 LoreLab 更新清单。")
    return value


@contextlib.contextmanager
def unpack(path: Path):
    if path.is_dir():
        yield path.resolve()
        return
    with tempfile.TemporaryDirectory(prefix="lorelab-update-") as temporary:
        directory = Path(temporary)
        with tarfile.open(path, "r:gz") as archive:
            entries = archive.getmembers()
            if len(entries) > 50000 or sum(e.size for e in entries) > MAX_BYTES:
                raise ValueError("安装包展开后过大。")
            names = set()
            for entry in entries:
                name = PurePosixPath(entry.name)
                if (name.is_absolute() or ".." in name.parts or entry.name in names
                        or not (entry.isfile() or entry.isdir())):
                    raise ValueError("安装包包含越界、重复或非普通文件。")
                names.add(entry.name)
            archive.extractall(directory, filter="data")
        roots = [p.parent.parent for p in directory.glob("*/packaging/bundle.json")]
        if (directory / "packaging/bundle.json").is_file():
            roots.append(directory)
        if len(roots) != 1:
            raise ValueError("安装包必须包含且仅包含一个完整 LoreLab bundle。")
        yield roots[0]


def update(args):
    prefix, before = maintenance.managed_installation()
    install = maintenance.installer()
    repo, ref = getattr(args, "repo", None), getattr(args, "ref", None)
    if repo and (args.source or args.feed) or ref and (args.source or args.feed):
        raise ValueError("--repo/--ref 不能与 --from/--feed 同时使用。")
    if args.source and args.feed:
        raise ValueError("--from 与 --feed 互斥。")
    saved = install.settings(prefix)
    local_source = (args.source and "://" not in args.source and Path(args.source).expanduser().is_dir()
                    and not (Path(args.source).expanduser() / "packaging/bundle.json").is_file())
    if repo or ref or local_source or not args.source and not args.feed and saved.get("source"):
        from .source_updates import update_source

        if args.sha256:
            raise ValueError("源码更新通过 Git 提交及组件锁校验；--sha256 仅用于旧安装包。")
        return update_source(args, prefix, before, install)
    source, expected, feed = args.source, args.sha256, None
    if not source:
        location = args.feed or install.settings(prefix).get("update_feed")
        if not location:
            raise ValueError("尚未配置更新源。使用 lorelab update --from 本地仓库，或 --repo 仓库地址 --ref 分支。")
        feed = read_feed(location)
        source, expected = feed["url"], feed.get("sha256")
        if feed.get("platform") != install.platform_tag():
            raise ValueError("更新清单的平台与本机不符。")
        if "://" not in source:
            if str(location).startswith("https://"):
                source = urllib.parse.urljoin(location, source)
            else:
                source = str(Path(location).expanduser().resolve().parent / source)
    source = validate_location(source)
    cached = False
    if source.startswith("https://"):
        path, cached = download(source, expected, prefix / "toolchain/downloads")
    else:
        path = Path(source)
        if expected and (not path.is_file() or sha256(path) != expected.lower()):
            raise ValueError("本地安装包 SHA256 不匹配。")
    try:
        with unpack(path) as root:
            # 校验由当前受信安装器执行，不执行候选包中的安装代码。
            bundle = install.verify_bundle(root)
            if feed and feed.get("bundle_id") and feed["bundle_id"] != bundle["release_id"]:
                raise ValueError("更新清单与包的 bundle_id 不一致。")
            previous = json.loads((before / "runtime.json").read_text(encoding="utf-8"))
            identity = previous.get("source_fingerprint")
            if identity is None and (before / "source/packaging/bundle.json").is_file():
                identity = json.loads((before / "source/packaging/bundle.json").read_text(encoding="utf-8"))["release_id"]
            if args.check:
                return {"ok": True, "available": identity != bundle["release_id"],
                        "bundle_id": bundle["release_id"], "download_cached": cached, "installed": False}
            release = install.install(root, prefix, force=args.force)
    except (tarfile.TarError, EOFError) as exc:
        raise ValueError("无法读取完整的 tar.gz 安装包；当前安装不变。") from exc
    return {"ok": True, "changed": release != before, "release": str(release),
            "bundle_id": bundle["release_id"], "download_cached": cached,
            "configuration_and_tasks": "preserved"}
