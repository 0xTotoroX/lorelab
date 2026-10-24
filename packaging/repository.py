"""[INPUT]: Agent 选定的本地源码、Git 仓库及 ref。
[OUTPUT]: 内容指纹、来源记录、独立候选快照；保留开发者工作区。
[POS]: 源码安装与更新复用的 Git 边界，不执行 pull/reset 或猜远端地址。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import contextlib
import hashlib
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from common import PackagingError, run, sha256, source_files


def fingerprint(root, files=None):
    files = source_files(root) if files is None else files
    return "source-" + hashlib.sha256(
        "".join(f"{name}:{sha256(root / name)}\n" for name in files).encode()).hexdigest()[:16]


def validate_repository(value):
    if not isinstance(value, str) or not value or value.startswith("-") or any(c in value for c in "\r\n\0"):
        raise PackagingError("invalid repository location")
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or parsed.password:
            raise PackagingError("use a local repository or HTTPS/SSH without embedded credentials")
        if parsed.scheme == "https" and parsed.username:
            raise PackagingError("repository credentials belong in the Git credential manager")
    elif not re.match(r"[\w.-]+@[\w.-]+:.+", value):
        if not Path(value).expanduser().exists():
            raise PackagingError("local source repository does not exist")
        value = str(Path(value).expanduser().resolve())
    return value


def provenance(root):
    if not (root / ".git").exists():
        return None
    revision = run(["git", "rev-parse", "HEAD"], cwd=root, capture=True).stdout.strip()
    branch = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root,
                            text=True, encoding="utf-8", capture_output=True, check=False)
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root,
                            text=True, encoding="utf-8", capture_output=True, check=False)
    location = remote.stdout.strip() if remote.returncode == 0 else str(root)
    return {"repository": validate_repository(location), "ref": branch.stdout.strip() or revision,
            "revision": revision, "checkout": str(root)}


@contextlib.contextmanager
def snapshot(repository, ref, cache):
    repository = validate_repository(repository)
    ref = ref or "HEAD"
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", ref) or ref.startswith("-") or ".." in ref:
        raise PackagingError("invalid repository ref")
    key = hashlib.sha256(repository.encode()).hexdigest()[:20]
    bare = cache / key
    bare.mkdir(parents=True, exist_ok=True)
    if not (bare / "HEAD").is_file():
        run(["git", "init", "--bare", bare], capture=True)
    # Git 自己管理凭据；不把凭据放入参数、日志或仓库内配置。
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    run(["git", "-C", bare, "fetch", "--no-tags", "--depth=1", "--", repository, ref], env=env)
    revision = run(["git", "-C", bare, "rev-parse", "FETCH_HEAD"], capture=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="lorelab-source-") as temp:
        directory = Path(temp)
        archive = directory / "source.tar"
        run(["git", "-C", bare, "archive", "--format=tar", "--output", archive, revision])
        root = directory / "source"
        root.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
        yield root, {"repository": repository, "ref": ref, "revision": revision}
