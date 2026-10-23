#!/usr/bin/env python3
"""隔离安装完整 LoreHub，检查成功后原子切换 current。

[INPUT]: 完整源码或校验通过的 bundle、prefix、可选 skills-dir。
[OUTPUT]: 独立 release、绝对路径 runtime.json 与稳定命令/Skill 链接。
[POS]: packaging 安装事务；不读写用户账号或调用云端业务接口。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
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
    run,
    sha256,
    source_files,
    uv_environment,
    verify_bundle,
    verify_components,
    verify_inputs,
    write_json,
)


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def require_directory(path: Path) -> None:
    if path.is_symlink() or lexists(path) and not path.is_dir():
        raise PackagingError(f"refusing non-directory/symlink: {path}")


def check_link(path: Path, target: Path) -> None:
    if not lexists(path):
        return
    if path.is_symlink() and os.path.abspath(path.parent / os.readlink(path)) == str(target):
        return
    raise PackagingError(f"refusing to overwrite existing non-LoreHub path: {path}")


def check_destinations(prefix: Path, skills_dir: Path | None) -> None:
    for directory in [prefix / "releases", prefix / "bin"]:
        require_directory(directory)
    current = prefix / "current"
    if lexists(current):
        if not current.is_symlink():
            raise PackagingError(f"refusing non-LoreHub current: {current}")
        target = current.resolve()
        try:
            runtime = json.loads((target / "runtime.json").read_text())
        except (OSError, ValueError) as error:
            raise PackagingError("existing current has no LoreHub runtime") from error
        if (target.parent != prefix / "releases" or runtime.get("product") != "lorehub"
                or runtime.get("release_id") != target.name):
            raise PackagingError("existing current is not owned by this LoreHub prefix")
    for name in COMMANDS:
        check_link(prefix / "bin" / name, prefix / "current/bin" / name)
    if skills_dir is not None:
        require_directory(skills_dir)
        if skills_dir == prefix or any(skills_dir.is_relative_to(prefix / part)
                                      for part in ("releases", "current", "bin")):
            raise PackagingError("skills-dir must not overlap releases/current/bin or equal prefix")
        for name in SKILLS:
            check_link(skills_dir / name, prefix / "current/skills" / name)


def write_launcher(path: Path, command: list[Path | str], environment: dict[str, str]) -> None:
    # shlex.quote 保留空格、单引号与 shell 元字符；不经 PATH 查找组件。
    exports = "".join(f"export {key}={shlex.quote(value)}\n" for key, value in environment.items())
    text = "#!/bin/sh\nunset PYTHONPATH PYTHONHOME\n" + exports
    text += "exec " + " ".join(shlex.quote(str(arg)) for arg in command) + ' "$@"\n'
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def prepare_runtime(release: Path) -> dict:
    source = release / "source"
    python = release / "venv/bin/python"
    binary = release / "bin/cubox-cli"
    binary.parent.mkdir()
    shutil.copy2(source / "packaging/prebuilt/cubox-cli", binary)
    binary.chmod(0o755)
    mubu = source / "modules/mubu-cli/scripts/mubu_api.py"
    tools = {"cubox": [str(binary)], "soota": [str(release / "venv/bin/soota")],
             "mubu": [str(python), str(mubu)]}
    runtime = {"schema_version": 1, "product": "lorehub", "release_id": release.name, "tools": tools,
               "components_lock_sha256": sha256(source / "components.lock.json")}
    write_json(release / "runtime.json", runtime)
    environment = {"LOREHUB_ROOT": str(source), "LOREHUB_RUNTIME_FILE": str(release / "runtime.json"),
                   "SOOTA_AUTO_UPDATE": "false", "CUBOX_NO_UPDATE_NOTIFIER": "1", "PYTHONNOUSERSITE": "1",
                   "PYTHONDONTWRITEBYTECODE": "1"}
    write_launcher(release / "bin/lorehub", [python, "-I", "-B", "-m", "lorehub.cli"], environment)
    write_launcher(release / "bin/soota", tools["soota"], environment)
    # 幕布脚本依靠相邻 mubu/ 导入，不能加会移除脚本目录的 -I。
    write_launcher(release / "bin/mubu-cli", tools["mubu"], environment)
    (release / "skills").mkdir()
    for name, path in SKILLS.items():
        (release / "skills" / name).symlink_to(f"../source/{path}", target_is_directory=True)
    return runtime


def install_environment(release: Path, uv: Path) -> None:
    env = uv_environment(release / "toolchain")
    python = create_venv(uv, release / "venv", env)
    wheels = sorted((release / "source/packaging/wheels").glob("*.whl"))
    if not wheels:
        raise PackagingError("bundle contains no dependency wheels")
    run([uv, "--no-config", "pip", "install", "--python", python, "--no-index", "--no-deps", *wheels], env=env)
    run([uv, "--no-config", "pip", "check", "--python", python], env=env)
    shutil.rmtree(release / "toolchain/cache", ignore_errors=True)


def smoke_check(release: Path) -> None:
    # 使用临时 HOME 和纯系统 PATH；--help/version 不登录、不读取真实用户资料。
    with tempfile.TemporaryDirectory(prefix="lorehub-smoke-") as temporary:
        env = {"HOME": temporary, "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
               "XDG_CONFIG_HOME": temporary + "/config", "XDG_CACHE_HOME": temporary + "/cache",
               "SOOTA_AUTO_UPDATE": "false", "CUBOX_NO_UPDATE_NOTIFIER": "1"}
        for name in COMMANDS:
            argument = "version" if name == "cubox-cli" else "--help"
            run([release / "bin" / name, argument], env=env, capture=True, timeout=30)
    verify_components(release / "source", release / "venv/bin/python")


def activate(prefix: Path, release: Path, skills_dir: Path | None) -> None:
    check_destinations(prefix, skills_dir)
    links = [(prefix / "bin" / name, Path("../current/bin") / name) for name in COMMANDS]
    if skills_dir is not None:
        links += [(skills_dir / name, prefix / "current/skills" / name) for name in SKILLS]
    created = []
    pending = prefix / f".current-{uuid.uuid4().hex}"
    try:
        for link, target in links:
            link.parent.mkdir(parents=True, exist_ok=True)
            if not lexists(link):
                link.symlink_to(target)
                created.append(link)
        pending.symlink_to(Path("releases") / release.name, target_is_directory=True)
        # 最后一个可能失败的操作；已有入口与 Skills 都通过 current 同时换代。
        os.replace(pending, prefix / "current")
    except BaseException:
        for link in reversed(created):
            link.unlink()
        raise
    finally:
        pending.unlink(missing_ok=True)


def install(root: Path, prefix: Path, skills_dir: Path | None = None) -> Path:
    root = root.resolve()
    prefix = prefix.expanduser().resolve()
    skills_dir = Path(os.path.abspath(skills_dir.expanduser())) if skills_dir is not None else None
    bundle = verify_bundle(root) if (root / BUNDLE).is_file() else None
    if bundle is None and any((root / "packaging" / part).exists() for part in ("prebuilt", "wheels")):
        raise PackagingError("prebuilt payload has no bundle manifest; refusing source-build fallback")
    verify_inputs(root)
    # 避免将安装目录递归收入源码包。
    if prefix == root or prefix.is_relative_to(root):
        raise PackagingError("prefix must be outside the source directory")
    prefix.mkdir(parents=True, exist_ok=True)
    lock_path = prefix / ".install.lock"
    if lock_path.is_symlink():
        raise PackagingError("refusing symlink install lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PackagingError("another installation is using this prefix") from error
        check_destinations(prefix, skills_dir)
        (prefix / "releases").mkdir(exist_ok=True)
        files = list(bundle["files"]) + [BUNDLE] if bundle else source_files(root)
        fingerprint = bundle["release_id"] if bundle else "source-" + hashlib.sha256(
            "".join(f"{name}:{sha256(root / name)}\n" for name in files).encode()).hexdigest()[:16]
        release = prefix / "releases" / f"{fingerprint}-{uuid.uuid4().hex[:8]}"
        release.mkdir()
        try:
            copy_source(root, release / "source", files)
            if bundle:
                verify_bundle(release / "source")
            verify_inputs(release / "source")
            uv = get_uv(release / "source", release / ".bootstrap")
            if bundle is None:
                build_payload(release / "source", release / ".build", uv)
                shutil.rmtree(release / ".build")
            install_environment(release, uv)
            prepare_runtime(release)
            smoke_check(release)
            shutil.rmtree(release / ".bootstrap", ignore_errors=True)
            activate(prefix, release, skills_dir)
        except BaseException:
            shutil.rmtree(release)
            raise
    return release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--skills-dir", type=Path)
    args = parser.parse_args()
    try:
        release = install(Path(__file__).resolve().parents[1], args.prefix, args.skills_dir)
        print(f"Installed LoreHub: {release}\nCommands: {release.parent.parent / 'bin'}")
        return 0
    except (PackagingError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"installation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
