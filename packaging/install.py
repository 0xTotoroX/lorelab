#!/usr/bin/env python3
"""隔离安装完整 LoreLab，兼容已有 LoreHub prefix，检查成功后原子切换 current。

[INPUT]: 完整源码或校验通过的 bundle、prefix、可选 skills-dir。
[OUTPUT]: 独立 release、命令/Skill 注册；Windows 入口独占创建并随激活事务安全回滚。
[POS]: packaging 安装事务；不读写用户账号或调用云端业务接口。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    BUNDLE,
    COMMANDS,
    SKILLS,
    PackagingError,
    build_payload,
    copy_source,
    create_venv,
    get_uv,
    platform_tag,  # noqa: F401 -- 产品 update 复用安装器平台判断
    product_name,
    run,
    sha256,
    source_files,
    uv_environment,
    verify_bundle,
    verify_components,
    verify_inputs,
    write_json,
)
from platform_support import (
    directory_link,
    exclusive_lock,
    executable,
    is_link,
    link_target,
    remove_link,
    switch_directory,
    venv_bin,
    windows,
)
from repository import fingerprint as source_fingerprint
from repository import provenance


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def require_directory(path: Path) -> None:
    if is_link(path) or lexists(path) and not path.is_dir():
        raise PackagingError(f"refusing non-directory/symlink: {path}")


def link_points_to(path: Path, target: Path) -> bool:
    # 只认安装器建立的固定路径，不沿任意用户软链接推断归属。
    if not is_link(path):
        return False
    destination = link_target(path)
    if os.path.abspath(destination) != str(target):
        return False
    # 含「其他软链接/..」的目标不能只用字符串归一化后就视作本 prefix。
    try:
        return destination.resolve() == target.resolve()
    except (OSError, RuntimeError):
        return False


def check_link(path: Path, target: Path) -> None:
    if windows() and path.suffix == ".exe":
        from windows_entries import owned

        if (not lexists(path) and not lexists(Path(str(path) + ".json"))) or owned(path, target):
            return
        raise PackagingError(f"refusing non-LoreLab Windows entry: {path}")
    if not lexists(path):
        return
    if link_points_to(path, target):
        return
    raise PackagingError(f"refusing to overwrite existing non-LoreLab/LoreHub path: {path}")


def check_destinations(prefix: Path, skills_dir: Path | None) -> None:
    for directory in [prefix / "releases", prefix / "bin"]:
        require_directory(directory)
    current = prefix / "current"
    if lexists(current):
        if not is_link(current):
            raise PackagingError(f"refusing non-LoreLab/LoreHub current: {current}")
        target = current.resolve()
        try:
            runtime = json.loads((target / "runtime.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PackagingError("existing current has no LoreLab/LoreHub runtime") from error
        if (target.parent != prefix / "releases" or runtime.get("product") not in {"lorelab", "lorehub"}
                or runtime.get("release_id") != target.name):
            raise PackagingError("existing current is not owned by this LoreLab/LoreHub prefix")
    for name in COMMANDS:
        check_link(prefix / "bin" / executable(name), prefix / "current/bin" / executable(name))
    if skills_dir is not None:
        require_directory(skills_dir)
        if skills_dir == prefix or any(skills_dir.is_relative_to(prefix / part)
                                      for part in ("releases", "current", "bin")):
            raise PackagingError("skills-dir must not overlap releases/current/bin or equal prefix")
        for name in SKILLS:
            check_link(skills_dir / name, prefix / "current/skills" / name)


def write_launcher(path: Path, command: list[Path | str], environment: dict[str, str]) -> None:
    if windows():
        path = path.with_suffix(".exe")
        shutil.copy2(path.parent.parent / "source/packaging/prebuilt/launcher.exe", path)
        write_json(Path(str(path) + ".json"), {"command": [str(p) for p in command], "environment": environment})
        return
    # shlex.quote 保留空格、单引号与 shell 元字符；不经 PATH 查找组件。
    exports = "".join(f"export {key}={shlex.quote(value)}\n" for key, value in environment.items())
    text = "#!/bin/sh\nunset PYTHONPATH PYTHONHOME\n" + exports
    text += "exec " + " ".join(shlex.quote(str(arg)) for arg in command) + ' "$@"\n'
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def prepare_runtime(release: Path) -> dict:
    source = release / "source"
    python = venv_bin(release / "venv")
    binary = release / "bin" / executable("cubox-cli")
    binary.parent.mkdir()
    shutil.copy2(source / "packaging/prebuilt" / executable("cubox-cli"), binary)
    binary.chmod(0o755)
    mubu = source / "modules/mubu-cli/scripts/mubu_api.py"
    tools = {"cubox": [str(binary)], "soota": [str(venv_bin(release / "venv", "soota"))],
             "mubu": [str(python), str(mubu)]}
    runtime = {"schema_version": 1, "product": "lorelab", "release_id": release.name, "tools": tools,
               "source_root": str(source), "components_lock": str(source / "components.lock.json"),
               "components_lock_sha256": sha256(source / "components.lock.json")}
    write_json(release / "runtime.json", runtime)
    environment = {"LORELAB_ROOT": str(source), "LORELAB_RUNTIME_FILE": str(release / "runtime.json"),
                   "LOREHUB_ROOT": str(source), "LOREHUB_RUNTIME_FILE": str(release / "runtime.json"),
                   "SOOTA_KNOWLEDGE_RUNTIME_FILE": str(release / "runtime.json"),
                   "SOOTA_KNOWLEDGE_COMPONENTS_LOCK": str(source / "components.lock.json"),
                   "SOOTA_AUTO_UPDATE": "false", "CUBOX_NO_UPDATE_NOTIFIER": "1", "PYTHONNOUSERSITE": "1",
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    write_launcher(release / "bin/lorelab", [python, "-X", "utf8", "-I", "-B", "-m", "lorelab.cli"], environment)
    write_launcher(release / "bin/soota", tools["soota"], environment)
    # 幕布脚本依靠相邻 mubu/ 导入，不能加会移除脚本目录的 -I。
    write_launcher(release / "bin/mubu-cli", tools["mubu"], environment)
    (release / "skills").mkdir()
    for name, path in SKILLS.items():
        directory_link(release / "skills" / name, Path(f"../source/{path}"))
    return runtime


def install_environment(release: Path, uv: Path) -> None:
    # 固定版本解释器与下载缓存归 prefix；每个 release 仍有独立 venv。
    env = uv_environment(release.parent.parent / "toolchain")
    python = create_venv(uv, release / "venv", env)
    wheels = sorted((release / "source/packaging/wheels").glob("*.whl"))
    for package in (product_name(release / "source"), "soota"):
        if not any(wheel.name.startswith(f"{package}-") for wheel in wheels):
            raise PackagingError(f"bundle is missing its local {package} wheel; no registry fallback is allowed")
    run([uv, "--no-config", "pip", "install", "--python", python, "--no-index", "--no-deps", *wheels], env=env)
    run([uv, "--no-config", "pip", "check", "--python", python], env=env)


def smoke_check(release: Path) -> None:
    # 使用临时 HOME 和纯系统 PATH；--help/version 不登录、不读取真实用户资料。
    with tempfile.TemporaryDirectory(prefix="lorelab-smoke-") as temporary:
        env = {"HOME": temporary, "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
               "XDG_CONFIG_HOME": temporary + "/config", "XDG_CACHE_HOME": temporary + "/cache",
               "SOOTA_AUTO_UPDATE": "false", "CUBOX_NO_UPDATE_NOTIFIER": "1", "PYTHONUTF8": "1"}
        if windows():
            env.update({k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC"}})
            env.update(USERPROFILE=temporary, APPDATA=temporary + "/roaming", LOCALAPPDATA=temporary + "/local",
                       TEMP=temporary, TMP=temporary, PATH=os.environ.get("SystemRoot", "C:\\Windows") + "\\System32")
        for name in COMMANDS:
            argument = "version" if name == "cubox-cli" else "--help"
            run([release / "bin" / executable(name), argument], env=env, capture=True, timeout=30)
    verify_components(release / "source", venv_bin(release / "venv"))


def settings(prefix: Path) -> dict:
    path = prefix / "install.json"
    if path.is_symlink():
        raise PackagingError("refusing symlink install record")
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1}
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PackagingError("unsupported install record")
    for key in ("skills_dirs", "bin_dirs"):
        items = value.get(key, [])
        if not isinstance(items, list) or not all(isinstance(p, str) and Path(p).is_absolute() for p in items):
            raise PackagingError(f"invalid install record: {key}")
    return value


def registration(prefix: Path, skills_dir=None, bin_dir=None, changes=None) -> tuple[dict, list]:
    value = settings(prefix)
    if changes:
        value.update(changes)
    for key, extra in (("skills_dirs", skills_dir), ("bin_dirs", bin_dir)):
        paths = value.get(key, [])
        if extra is not None:
            paths = [*paths, os.path.abspath(Path(extra).expanduser())]
        value[key] = sorted(set(paths))
    check_destinations(prefix, None)
    links = [(prefix / "bin" / executable(name), Path("../current/bin") / executable(name)) for name in COMMANDS]
    for path in value["skills_dirs"]:
        directory = Path(path)
        check_destinations(prefix, directory)
        links += [(directory / name, prefix / "current/skills" / name) for name in SKILLS]
    for path in value["bin_dirs"]:
        directory = Path(path)
        require_directory(directory)
        if directory == prefix / "bin":
            continue
        if directory == prefix or directory.is_relative_to(prefix):
            raise PackagingError("external bin-dir must be outside the installation prefix")
        for name in COMMANDS:
            name = executable(name)
            check_link(directory / name, prefix / "bin" / name)
            links.append((directory / name, prefix / "bin" / name))
    targets = {}
    for link, target in links:
        normalized = os.path.abspath(link.parent / target)
        if link in targets and targets[link] != normalized:
            raise PackagingError("Skill and CLI registration directories overlap")
        targets[link] = normalized
    return value, links


def activate(prefix: Path, release: Path, skills_dir: Path | None, bin_dir=None, changes=None) -> None:
    value, links = registration(prefix, skills_dir, bin_dir, changes)
    obsolete = [(prefix / "bin/lorehub", prefix / "current/bin/lorehub")]
    for directory in value["skills_dirs"]:
        obsolete.append((Path(directory) / "lorehub", prefix / "current/skills/lorehub"))
    created = []
    retired = []
    pending = prefix / f".current-{uuid.uuid4().hex}"
    record = prefix / "install.json"
    before = record.read_bytes() if record.exists() else None
    record_pending = prefix / f".install-{uuid.uuid4().hex}.json"
    saved = False
    first_current = windows() and not lexists(prefix / "current")
    windows_created = set()
    # Windows 文件句柄跨越整个激活事务：异常时按句柄删除，提交后才解除独占。
    with contextlib.ExitStack() as entries:
        try:
            directory_link(pending, Path("releases") / release.name)
            # junction 的目标须已存在；首次安装的入口在检查完成后才暂时公开，失败撤回。
            if first_current:
                switch_directory(pending, prefix / "current")
            for link, target in links:
                link.parent.mkdir(parents=True, exist_ok=True)
                if link in windows_created:
                    continue
                absolute = Path(os.path.abspath(link.parent / target))
                if lexists(link):
                    # 预检后可能有其他安装注册到同一目录，不能静默接受新出现的外部入口。
                    check_link(link, absolute)
                    continue
                if windows() and link.suffix == ".exe":
                    from windows_entries import create

                    entries.enter_context(create(link, absolute, release / "source/packaging/prebuilt/launcher.exe"))
                    windows_created.add(link)
                elif windows():
                    directory_link(link, target)
                    created.append((link, target))
                else:
                    link.symlink_to(target)
                    created.append((link, target))
            # 退役发生在切换前，记录原始链接文本，异常时恢复旧入口。
            for link, target in obsolete:
                if link_points_to(link, target):
                    original = os.readlink(link)
                    link.unlink()
                    retired.append((link, original))
            data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
            if data != before:
                record_pending.write_bytes(data)
                record_pending.chmod(0o600)
                os.replace(record_pending, record)
                saved = True
            # 最后一个可能失败的操作；此后不再清理旧链接或旧 release。
            if not first_current:
                switch_directory(pending, prefix / "current")
        except BaseException:
            if saved:
                record.write_bytes(before) if before is not None else record.unlink()
            for link, original in reversed(retired):
                link.symlink_to(original)
            for link, target in reversed(created):
                if link_points_to(link, Path(os.path.abspath(link.parent / target))):
                    remove_link(link)
            if first_current and link_points_to(prefix / "current", release):
                remove_link(prefix / "current")
            remove_link(pending)
            raise
        finally:
            record_pending.unlink(missing_ok=True)


@contextlib.contextmanager
def installation_lock(prefix: Path):
    prefix.mkdir(parents=True, exist_ok=True)
    lock_path = prefix / ".install.lock"
    if lock_path.is_symlink():
        raise PackagingError("refusing symlink install lock")
    try:
        with exclusive_lock(lock_path):
            yield
    except BlockingIOError as error:
        raise PackagingError("another installation is using this prefix") from error


def install(root: Path, prefix: Path, skills_dir: Path | None = None, bin_dir: Path | None = None,
            *, force: bool = False, source_origin: dict | None = None) -> Path:
    root = root.resolve()
    prefix = prefix.expanduser().resolve()
    skills_dir = Path(os.path.abspath(skills_dir.expanduser())) if skills_dir is not None else None
    bundle = verify_bundle(root) if (root / BUNDLE).is_file() else None
    if bundle is None and any((root / "packaging" / part).exists() for part in ("prebuilt", "wheels")):
        raise PackagingError("prebuilt payload has no bundle manifest; refusing source-build fallback")
    verify_inputs(root)
    origin = source_origin or (provenance(root) if bundle is None else None)
    changes = {"source": origin} if origin else {}
    # 避免将安装目录递归收入源码包。
    if prefix == root or prefix.is_relative_to(root):
        raise PackagingError("prefix must be outside the source directory")
    with installation_lock(prefix):
        registration(prefix, skills_dir, bin_dir)
        (prefix / "releases").mkdir(exist_ok=True)
        files = list(bundle["files"]) + [BUNDLE] if bundle else source_files(root)
        fingerprint = bundle["release_id"] if bundle else source_fingerprint(root, files)
        current = (prefix / "current").resolve()
        if not force and (current / "runtime.json").is_file():
            previous = json.loads((current / "runtime.json").read_text(encoding="utf-8"))
            previous_bundle = current / "source" / BUNDLE
            identity = previous.get("source_fingerprint")
            if identity is None and previous_bundle.is_file():
                identity = json.loads(previous_bundle.read_text(encoding="utf-8")).get("release_id")
            if identity == fingerprint:
                if previous_bundle.is_file():
                    verify_bundle(current / "source")
                else:
                    for name in files:
                        if sha256(current / "source" / name) != sha256(root / name):
                            raise PackagingError("installed source changed; use --force to repair in a new release")
                smoke_check(current)
                activate(prefix, current, skills_dir, bin_dir, changes)
                return current
        release = prefix / "releases" / f"{fingerprint}-{uuid.uuid4().hex[:8]}"
        release.mkdir()
        try:
            copy_source(root, release / "source", files)
            if bundle:
                verify_bundle(release / "source")
            verify_inputs(release / "source")
            uv = get_uv(release / "source", prefix / "toolchain")
            if bundle is None:
                build_payload(release / "source", release / ".build", uv, prefix / "toolchain")
                shutil.rmtree(release / ".build")
            install_environment(release, uv)
            manifest = prepare_runtime(release)
            manifest["source_fingerprint"] = fingerprint
            manifest["source_files"] = files if bundle is None else None
            write_json(release / "runtime.json", manifest)
            smoke_check(release)
            shutil.rmtree(release / ".bootstrap", ignore_errors=True)
            activate(prefix, release, skills_dir, bin_dir, changes)
        except BaseException:
            shutil.rmtree(release)
            raise
    return release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local/share/lorelab")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--skills-dir", type=Path)
    group.add_argument("--no-skills", action="store_true")
    bins = parser.add_mutually_exclusive_group()
    bins.add_argument("--bin-dir", type=Path)
    bins.add_argument("--no-bin", action="store_true")
    parser.add_argument("--force", action="store_true", help="在新 release 修复安装，不修改旧版本")
    parser.add_argument("--source-origin", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        prefix = args.prefix.expanduser().resolve()
        saved = settings(prefix)
        skills = None if args.no_skills else args.skills_dir
        bins = None if args.no_bin else args.bin_dir
        if not args.no_skills and skills is None and not saved.get("skills_dirs"):
            skills = Path.home() / ".agents/skills"
        if not args.no_bin and bins is None and not saved.get("bin_dirs"):
            bins = Path.home() / ".local/bin"
        before = (prefix / "current").resolve()
        origin = json.loads(args.source_origin.read_text(encoding="utf-8")) if args.source_origin else None
        release = install(Path(__file__).resolve().parents[1], prefix, skills, bins, force=args.force,
                          source_origin=origin)
        print(json.dumps({"ok": True, "changed": release != before, "release": str(release),
                          "commands": str(prefix / "bin"), "next": str(prefix / "bin" / executable("lorelab")) + " setup"}))
        return 0
    except (PackagingError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"installation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
