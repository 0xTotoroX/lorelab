"""本地组件指纹、锁定和独立源码导出。

[INPUT]: components.lock.json、组件源码与各自的 Skill 闭包。
[OUTPUT]: verify(root)、refresh(root)、export_component(root, name, destination)。
[POS]: LoreHub 的本地组件维护层；不访问远端或改动导入来源 revision。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

LOCK_FILE = "components.lock.json"
PROVENANCE_FILE = "lorehub-provenance.json"

# 仅排除明确的生成物；不读取 .gitignore，也不按扩展名排除 JSON、文档或测试数据。
_CACHE_DIRS = frozenset({
    ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".cache", "node_modules", "dist", "build", "htmlcov",
})
_RUNTIME_ROOTS = frozenset({".private", ".local", "output", "tmp", ".config", ".state"})
_RUNTIME_FILES = frozenset({".DS_Store", ".coverage", ".mubu_token", ".mubu_trash.json"})
_EXAMPLE_ENV_SUFFIXES = (".example", ".sample", ".template")


def _excluded(relative: PurePosixPath, *, is_dir: bool) -> bool:
    parts = relative.parts
    name = relative.name
    if any(part in _CACHE_DIRS or part.endswith(".egg-info") for part in parts):
        return True
    if parts[0] in _RUNTIME_ROOTS or parts[:2] == ("docs", "private"):
        return True
    if len(parts) == 1 and name in {"PLAN.md", "PLAN.zh-CN.md", "cubox-cli", "cubox-cli.exe"}:
        return True
    if parts in {("bin", "cubox-cli"), ("bin", "cubox-cli.exe")}:
        return True
    if is_dir:
        return False
    return (
        name in _RUNTIME_FILES
        or name.startswith(".coverage.")
        or name.endswith((".pyc", ".pyo"))
        or (name == ".env" or name.startswith(".env.")) and not name.endswith(_EXAMPLE_ENV_SUFFIXES)
    )


def _relative_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"{label}: expected a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{label}: unsafe path {value!r}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label}: control characters are not allowed")
    return path


def _safe_path(root: Path, value: Any, label: str) -> Path:
    relative = _relative_path(value, label)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"{label}: symbolic links are not supported ({value})")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"{label}: path escapes the product root")
    return path


def _load(root: Path) -> dict[str, Any]:
    path = root / LOCK_FILE
    if path.is_symlink():
        raise ValueError(f"{LOCK_FILE}: symbolic links are not supported")
    lock = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(lock, dict) or type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
        raise ValueError(f"{LOCK_FILE}: expected schema_version 1")
    components = lock.get("components")
    if not isinstance(components, dict) or not components:
        raise ValueError(f"{LOCK_FILE}: components must be a nonempty object")
    return lock


def _component_paths(root: Path, name: str, entry: Any) -> tuple[Path, Path]:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or not isinstance(entry, dict):
        raise ValueError(f"{name!r}: invalid component entry")
    path = _safe_path(root, entry.get("path"), f"{name}.path")
    if _excluded(PurePosixPath(entry["path"]), is_dir=True):
        raise ValueError(f"{name}.path: cannot use a runtime or cache directory as component source")
    if not path.is_dir():
        raise ValueError(f"{name}.path: component directory is missing")
    skill = entry.get("skill")
    if not isinstance(skill, dict) or not isinstance(skill.get("name"), str) or not skill["name"]:
        raise ValueError(f"{name}.skill: name and path are required")
    skill_path = _safe_path(root, skill.get("path"), f"{name}.skill.path")
    if not skill_path.is_relative_to(path) or not skill_path.is_dir():
        raise ValueError(f"{name}.skill.path: must be a directory inside this component")
    for key in ("repository", "revision", "version"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise ValueError(f"{name}.{key}: import provenance is required")
    return path, skill_path


def _files(path: Path) -> dict[str, str]:
    files: dict[str, str] = {}

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir()):
            relative = PurePosixPath(child.relative_to(path).as_posix())
            if _excluded(relative, is_dir=child.is_dir()):
                continue
            if child.is_symlink():
                raise ValueError(f"{relative}: symbolic links are not supported in component source")
            if child.is_dir():
                visit(child)
            elif child.is_file():
                files[str(relative)] = hashlib.sha256(child.read_bytes()).hexdigest()
            else:
                raise ValueError(f"{relative}: expected a regular source file")

    visit(path)
    return files


def _tree_sha256(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _inspect(root: Path, lock: dict[str, Any], *, compare: bool) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    result: dict[str, Any] = {"ok": True, "errors": [], "components": {}}
    snapshots: dict[str, dict[str, str]] = {}
    for name, entry in lock["components"].items():
        detail: dict[str, Any] = {"ok": False, "tree_sha256": None}
        result["components"][name] = detail
        try:
            path, skill_path = _component_paths(root, name, entry)
            files = _files(path)
            skill_entry = (skill_path / "SKILL.md").relative_to(path).as_posix()
            if skill_entry not in files:
                raise ValueError("Skill entrypoint is missing or excluded from the source fingerprint")
            actual = _tree_sha256(files)
            snapshots[name] = files
            detail.update({
                "path": entry["path"], "skill": dict(entry["skill"]),
                "recorded_revision": entry["revision"], "locked_tree_sha256": entry.get("tree_sha256"),
                "tree_sha256": actual, "file_count": len(files),
            })
            if compare and entry.get("tree_sha256") != actual:
                raise ValueError("source fingerprint differs from components.lock.json; review changes before refresh")
            detail["ok"] = True
        except (OSError, ValueError) as exc:
            result["errors"].append(f"{name}: {exc}")
    result["ok"] = not result["errors"]
    return result, snapshots


def _failure(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "errors": [str(exc)], "components": {}}


def verify(root: Path) -> dict[str, Any]:
    """只读核对全部组件；失败也返回 ok/errors，尽量保留各组件的实际指纹。"""
    try:
        root = Path(root).resolve(strict=True)
        result, _ = _inspect(root, _load(root), compare=True)
        return result
    except (OSError, ValueError) as exc:
        return _failure(exc)


def refresh(root: Path) -> dict[str, Any]:
    """原子更新全部 tree_sha256；路径无效时不写，保留 revision 及其他元数据。"""
    try:
        root = Path(root).resolve(strict=True)
        lock = _load(root)
        result, _ = _inspect(root, lock, compare=False)
        if not result["ok"]:
            return result
        for name, detail in result["components"].items():
            lock["components"][name]["tree_sha256"] = detail["tree_sha256"]
        lock_path = root / LOCK_FILE
        fd, temporary = tempfile.mkstemp(prefix=f".{LOCK_FILE}.", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(lock, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, stat.S_IMODE(lock_path.stat().st_mode))
            os.replace(temporary, lock_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return verify(root)
    except (OSError, ValueError) as exc:
        return _failure(exc)


def export_component(root: Path, name: str, destination: Path) -> dict[str, Any]:
    """导出已锁定源码副本；目标已存在、锁过期或路径不安全时抛出异常。"""
    root = Path(root).resolve(strict=True)
    lock = _load(root)
    if name not in lock["components"]:
        raise ValueError(f"Unknown component: {name}")
    result, snapshots = _inspect(root, lock, compare=True)
    if not result["ok"]:
        raise ValueError("; ".join(result["errors"]))
    entry = lock["components"][name]
    source, skill_path = _component_paths(root, name, entry)
    destination = Path(destination).absolute()
    if os.path.lexists(destination):
        raise FileExistsError(f"Export destination already exists: {destination}")
    resolved = destination.resolve()
    if resolved == root or any(
        resolved.is_relative_to(root / component["path"]) for component in lock["components"].values()
    ):
        raise ValueError("Export destination must be outside all component source directories")
    files = snapshots[name]
    if PROVENANCE_FILE in files:
        raise ValueError(f"Source already contains the reserved export file {PROVENANCE_FILE}")
    provenance = {
        "schema_version": 1, "component": name,
        "repository": entry["repository"], "recorded_revision": entry["revision"],
        "revision_role": "import_source", "version": entry["version"],
        "tree_sha256": result["components"][name]["tree_sha256"],
        "skill": {"name": entry["skill"]["name"], "path": skill_path.relative_to(source).as_posix()},
        "files": files,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()  # 独占创建，绝不覆盖已有目标，包括空目录。
    try:
        for relative, expected in files.items():
            original = _safe_path(source, relative, f"{name}.export")
            content = original.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"{name}: source changed during export: {relative}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(stat.S_IMODE(original.stat().st_mode))
        if _files(destination) != files or _files(source) != files:
            raise ValueError(f"{name}: source or destination changed during export")
        (destination / PROVENANCE_FILE).write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {
        "ok": True, "errors": [], "component": name, "destination": str(destination),
        "tree_sha256": provenance["tree_sha256"], "file_count": len(files),
        "provenance": str(destination / PROVENANCE_FILE),
    }
