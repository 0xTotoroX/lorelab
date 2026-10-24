"""构建与安装共用的输入、校验和本地工具链。

[INPUT]: 本地组件源码、组件锁、Python 依赖锁与 uv。
[OUTPUT]: 确定的源码选择、bundle 校验、Cubox/依赖 wheel 构建。
[POS]: packaging 的共享实现；不解析或更新组件指纹。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

PYTHON_VERSION = "3.12.12"
COMMANDS = ("lorelab", "cubox-cli", "soota", "mubu-cli")
SKILLS = {
    "lorelab": "skills/lorelab",
    "cubox": "modules/cubox-cli/skills/cubox",
    "soota": "modules/soota/skills/soota",
    "mubu-integration": "modules/mubu-cli",
}
ROOT_FILES = {"AGENTS.md", "LICENSE", "NOTICE.md", "pyproject.toml", "uv.lock", "components.lock.json", "install.sh",
              "README.md", "README.zh-CN.md", "THIRD_PARTY_NOTICES.md", "Install.command"}
ROOT_DIRS = {"src", "skills", "packaging", "docs", "tests", "LICENSES"}
MODULES = {"cubox-cli", "soota", "mubu-cli"}
EXCLUDED = {".git", ".private", "private", "dist", "build", "cache", ".cache", "__pycache__",
            ".venv", "venv", "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache",
            ".DS_Store", "PLAN.md", "PLAN.zh-CN.md", ".env", ".env.local", "runtime.json",
            ".local", "output", "tmp", ".config", ".state", ".mubu_token", ".mubu_trash.json", ".coverage"}
BUNDLE = "packaging/bundle.json"


class PackagingError(RuntimeError):
    pass


def run(args, *, cwd=None, env=None, capture=False, timeout=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, timeout=timeout)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or path.startswith("/") or any(p in EXCLUDED or p in {"..", "."} for p in parts):
        return False
    if parts[:2] in {("src", "lorehub"), ("skills", "lorehub")} or path.startswith("packaging/wheels/lorehub-"):
        return False
    if any(p.startswith((".env.", ".coverage."))
           or p.endswith((".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db")) for p in parts):
        return False
    return (len(parts) == 1 and parts[0] in ROOT_FILES or parts[0] in ROOT_DIRS
            or len(parts) > 2 and parts[0] == "modules" and parts[1] in MODULES)


def source_files(root: Path) -> list[str]:
    if (root / ".git").exists():
        candidates = run(["git", "ls-files", "-z"], cwd=root, capture=True).stdout.split("\0")
    else:
        candidates = [p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_dir()]
    result = []
    for name in sorted(set(candidates)):
        if not allowed(name) or name == BUNDLE or name.startswith(("packaging/wheels/", "packaging/prebuilt/")):
            continue
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise PackagingError(f"source must be a regular file: {name}")
        if not path.resolve().is_relative_to(root.resolve()):
            raise PackagingError(f"source escapes root: {name}")
        result.append(name)
    return result


def copy_source(root: Path, destination: Path, files: list[str]) -> None:
    destination.mkdir(parents=True)
    for name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)


def product_name(root: Path) -> str:
    name = json.loads((root / "components.lock.json").read_text())["product"]["name"]
    if name == "lorehub":
        raise PackagingError("LoreHub bundles require their original installer; this installer accepts LoreLab only")
    if name != "lorelab":
        raise PackagingError("unsupported product in components.lock.json")
    return name


def verify_components(root: Path, python: str | Path = sys.executable) -> None:
    product = product_name(root)
    if not (root / f"src/{product}/components.py").is_file():
        raise PackagingError(f"missing src/{product}/components.py: integrate verify(root) before building")
    code = """import importlib, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'src'))
result = importlib.import_module(sys.argv[2] + '.components').verify(root)
if not isinstance(result, dict) or result.get('ok') is not True:
    raise SystemExit('component verification failed: ' + str(result))
"""
    run([python, "-I", "-B", "-c", code, root, product])


def verify_inputs(root: Path) -> None:
    for name in [f"src/{product_name(root)}/cli.py", "packaging/requirements.lock",
                 "packaging/build-requirements.lock", "modules/mubu-cli/scripts/mubu_api.py",
                 *(f"{p}/SKILL.md" for p in SKILLS.values())]:
        if not (root / name).is_file():
            raise PackagingError(f"incomplete product source: missing {name}")
    verify_components(root)


def platform_tag() -> str:
    machine = {"aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine(), platform.machine())
    return f"{platform.system().lower()}-{machine}"


def inventory(root: Path) -> dict:
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if name == BUNDLE:
            continue
        if path.is_symlink():
            raise PackagingError(f"bundle cannot contain symlinks: {name}")
        if path.is_file():
            if not allowed(name):
                raise PackagingError(f"forbidden bundle file: {name}")
            result[name] = {"sha256": sha256(path), "mode": stat.S_IMODE(path.stat().st_mode)}
    return result


def seal_bundle(root: Path) -> dict:
    files = inventory(root)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    version = json.loads((root / "components.lock.json").read_text())["product"]["version"]
    value = {"schema_version": 1, "platform": platform_tag(), "release_id": f"{version}-{digest[:16]}",
             "components_lock_sha256": sha256(root / "components.lock.json"), "files": files}
    write_json(root / BUNDLE, value)
    return value


def verify_bundle(root: Path) -> dict:
    product_name(root)
    value = json.loads((root / BUNDLE).read_text())
    if value.get("schema_version") != 1 or value.get("platform") != platform_tag():
        raise PackagingError("unsupported bundle schema or platform")
    if value.get("files") != inventory(root):
        raise PackagingError("bundle file inventory/hash/mode mismatch")
    digest = hashlib.sha256(json.dumps(value["files"], sort_keys=True).encode()).hexdigest()
    version = json.loads((root / "components.lock.json").read_text())["product"]["version"]
    if value.get("release_id") != f"{version}-{digest[:16]}":
        raise PackagingError("bundle release_id mismatch")
    if value.get("components_lock_sha256") != sha256(root / "components.lock.json"):
        raise PackagingError("components lock checksum mismatch")
    return value


def get_uv(root: Path, scratch: Path) -> Path:
    current, legacy = os.environ.get("LORELAB_INSTALL_UV"), os.environ.get("LOREHUB_INSTALL_UV")
    if current and legacy and Path(current).resolve() != Path(legacy).resolve():
        raise PackagingError("conflicting LORELAB_INSTALL_UV and LOREHUB_INSTALL_UV")
    supplied = current or legacy
    uv = Path(supplied) if supplied else Path(run(
        ["/bin/sh", root / "packaging/uv.sh", scratch / "uv"], capture=True).stdout.strip())
    if not uv.is_absolute() or not uv.is_file():
        raise PackagingError("uv bootstrap did not return an absolute executable")
    return uv


def uv_environment(directory: Path) -> dict[str, str]:
    # 不继承会选择其他解释器、索引、安装目录或跳过哈希的用户 uv/pip 配置。
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("UV_", "PIP_", "PYTHON")) and k not in {"VIRTUAL_ENV", "CONDA_PREFIX"}}
    env.update(UV_PYTHON_INSTALL_DIR=str(directory / "python"), UV_CACHE_DIR=str(directory / "cache"),
               UV_PYTHON_INSTALL_BIN="false", UV_LINK_MODE="copy")
    return env


def create_venv(uv: Path, venv: Path, env: dict) -> Path:
    run([uv, "--no-config", "python", "install", "--no-bin", PYTHON_VERSION], env=env)
    run([uv, "--no-config", "venv", "--managed-python", "--python", PYTHON_VERSION, venv], env=env)
    return venv / "bin/python"


def build_payload(root: Path, scratch: Path, uv: Path) -> None:
    if platform_tag() != "darwin-arm64":
        raise PackagingError("release builds currently support native macOS arm64 only")
    go = shutil.which("go")
    if not go:
        raise PackagingError("source build requires Go; use the prebuilt release bundle without Go")
    lock = json.loads((root / "components.lock.json").read_text())
    cubox = root / "modules/cubox-cli"
    module = next(line.split()[1] for line in (cubox / "go.mod").read_text().splitlines()
                  if line.startswith("module "))
    binary = root / "packaging/prebuilt/cubox-cli"
    binary.parent.mkdir(parents=True)
    scratch = scratch.resolve()
    env = uv_environment(scratch)
    (scratch / "tmp").mkdir(parents=True)
    env["TMPDIR"] = str(scratch / "tmp")
    # 本地 C 扩展不能把发布者目录写入调试信息或 __FILE__；不复用外部 wheel 构建缓存。
    env["CFLAGS"] = "-g0 " + shlex.quote(f"-ffile-prefix-map={scratch}=/lorelab-build")
    env["CPPFLAGS"] = ""
    env["LDFLAGS"] = ""
    env.update(CGO_ENABLED="0", GOOS="darwin", GOARCH="arm64", GOWORK="off", GOFLAGS="")
    run([go, "build", "-mod=readonly", "-trimpath", "-buildvcs=false", "-ldflags",
         f"-s -w -X {module}/cmd.Version={lock['components']['cubox']['version']}", "-o", binary, "."],
        cwd=cubox, env=env)
    python = create_venv(uv, scratch / "venv", env)
    run([uv, "--no-config", "pip", "install", "--python", python, "--require-hashes",
         "-r", root / "packaging/build-requirements.lock"], env=env)
    wheels = root / "packaging/wheels"
    wheels.mkdir()
    # 源码依赖只在发布者机器构建一次；发行包安装仅使用已校验的 wheel。
    run([python, "-I", "-m", "pip", "--isolated", "--cache-dir", scratch / "pip-cache",
         "wheel", "--no-deps", "--no-build-isolation",
         "--require-hashes", "--wheel-dir", wheels, "-r", root / "packaging/requirements.lock"], env=env)
    run([python, "-I", "-m", "pip", "--isolated", "--cache-dir", scratch / "pip-cache",
         "wheel", "--no-index", "--no-deps", "--no-build-isolation",
         "--wheel-dir", wheels, root, root / "modules/soota"], env=env)
