"""统一准备 LoreLab 与 Soota 的版本元数据，不运行依赖解析器。

[INPUT]: 两包的 pyproject/__init__、两份 uv.lock、components.lock.json 与本地组件源码。
[OUTPUT]: versions(root) 只读核对版本；prepare(root, product_version, soota_version) 返回准备报告。
[POS]: 产品发布准备层；复用 components 的指纹刷新/验收，保留导入 revision。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import components

_PROJECTS = {"pyproject.toml": "lorelab", "modules/soota/pyproject.toml": "soota"}
_INITS = {"src/lorelab/__init__.py": "lorelab", "modules/soota/src/soota/__init__.py": "soota"}
_LOCKS = {"uv.lock": {"lorelab": ".", "soota": "modules/soota"}, "modules/soota/uv.lock": {"soota": "."}}
_PATHS = (*_PROJECTS, *_INITS, *_LOCKS, components.LOCK_FILE)
_LEGACY_SOOTA = "0.1.0+d0f20bc"
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_TABLE = re.compile(r"(?m)^[ \t]*\[")
_VALUE = re.compile(
    r"""(?m)^[ \t]*version[ \t]*=[ \t]*(?P<quote>["'])(?P<value>[^"'\r\n]*)(?P=quote)[ \t]*(?:\#[^\r\n]*)?\r?$"""
)


def _version(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ValueError(f"{label}: expected a strict X.Y.Z version, got {value!r}")
    return value


def _path(root: Path, relative: str) -> Path:
    path = root
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise ValueError(f"{relative}: symbolic links are not supported")
    return path


@dataclass(frozen=True)
class _Field:
    name: str
    value: str
    start: int
    end: int


def _toml_field(text: str, header: re.Match[str], name: str, value: Any, label: str) -> _Field:
    end = _TABLE.search(text, header.end())
    matches = list(_VALUE.finditer(text, header.end(), end.start() if end else len(text)))
    if len(matches) != 1 or matches[0]["value"] != value:
        raise ValueError(f"{label}: expected one literal version in the package table")
    match = matches[0]
    return _Field(name, _version(value, label), match.start("value"), match.end("value"))


def _headers(text: str, table: str) -> list[re.Match[str]]:
    return list(re.finditer(rf"(?m)^[ \t]*{table}[ \t]*(?:\#[^\r\n]*)?\r?$", text))


def _project(text: str, name: str, label: str) -> list[_Field]:
    project = tomllib.loads(text).get("project")
    if not isinstance(project, dict) or project.get("name") != name:
        raise ValueError(f"{label}: expected [project].name = {name!r}")
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list) or any(not isinstance(item, str) for item in dynamic) or "version" in dynamic:
        raise ValueError(f"{label}: project.version must be static")
    headers = _headers(text, r"\[[ \t]*project[ \t]*\]")
    if len(headers) != 1:
        raise ValueError(f"{label}: expected one [project] table")
    return [_toml_field(text, headers[0], name, project.get("version"), label)]


def _init(text: str, name: str, label: str) -> list[_Field]:
    try:
        tree = ast.parse(text, filename=label)
    except SyntaxError as exc:
        raise ValueError(f"{label}: invalid Python metadata: {exc}") from exc
    assignments = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__version__"
        )
        or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__version__")
    ]
    stores = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "__version__" and isinstance(node.ctx, ast.Store)
    ]
    if len(assignments) != 1 or len(stores) != 1:
        raise ValueError(f"{label}: expected one static __version__ assignment")
    value = assignments[0].value
    if not isinstance(value, ast.Constant):
        raise ValueError(f"{label}: __version__ must be a literal string")  # noqa: TRY004 - 元数据错误统一为 ValueError。
    version = _version(value.value, label)
    literal = ast.get_source_segment(text, value)
    if literal not in (f'"{version}"', f"'{version}'"):
        raise ValueError(f"{label}: __version__ must use a plain quoted string")
    # AST 的列偏移按 UTF-8 字节计数；不能把中文注释的字节数当作字符数。
    lines = text.splitlines(keepends=True)
    start = sum(map(len, lines[: value.lineno - 1]))
    start += len(lines[value.lineno - 1].encode("utf-8")[: value.col_offset].decode("utf-8")) + 1
    return [_Field(name, version, start, start + len(version))]


def _lock(text: str, packages: dict[str, str], label: str) -> list[_Field]:
    data = tomllib.loads(text)
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError(f"{label}: expected lock schema version 1")
    if "revision" in data and (type(data["revision"]) is not int or data["revision"] < 1):
        raise ValueError(f"{label}: invalid lock revision")
    entries = data.get("package")
    if not isinstance(entries, list) or not entries or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError(f"{label}: expected a nonempty [[package]] array")
    if any(not isinstance(entry.get(key), str) or not entry[key] for entry in entries for key in ("name", "version")):
        raise ValueError(f"{label}: each package needs a name and version")
    headers = _headers(text, r"\[\[[ \t]*package[ \t]*\]\]")
    if len(headers) != len(entries):
        raise ValueError(f"{label}: ambiguous [[package]] layout")
    fields = []
    for name, source in packages.items():
        indexes = [i for i, entry in enumerate(entries) if entry.get("name") == name]
        if len(indexes) != 1:
            raise ValueError(f"{label}: expected exactly one local package named {name!r}")
        index = indexes[0]
        entry = entries[index]
        if entry.get("source") not in ({"editable": source}, {"directory": source}):
            raise ValueError(f"{label}: {name}.source must refer to the local path {source!r}")
        fields.append(_toml_field(text, headers[index], name, entry.get("version"), f"{label}: {name}"))
    return fields


def _manifest(root: Path, text: str) -> dict[str, Any]:
    lock = json.loads(text)
    if not isinstance(lock, dict) or type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
        raise ValueError(f"{components.LOCK_FILE}: expected schema_version 1")
    product = lock.get("product")
    if not isinstance(product, dict) or product.get("name") != "lorelab":
        raise ValueError(f"{components.LOCK_FILE}: expected product.name = 'lorelab'")
    _version(product.get("version"), "product.version")
    entries = lock.get("components")
    if not isinstance(entries, dict) or not isinstance(entries.get("soota"), dict):
        raise ValueError(f"{components.LOCK_FILE}: components.soota is required")  # noqa: TRY004 - 公共异常契约。
    if entries["soota"].get("path") != "modules/soota":
        raise ValueError(f"{components.LOCK_FILE}: soota.path must be 'modules/soota'")
    for name, entry in entries.items():
        components._component_paths(root, name, entry)
        if "import_version" in entry and (not isinstance(entry["import_version"], str) or not entry["import_version"]):
            raise ValueError(f"{components.LOCK_FILE}: {name}.import_version must be a nonempty string")
    return lock


@dataclass
class _Metadata:
    root: Path
    originals: dict[str, bytes]
    modes: dict[str, int]
    fields: dict[str, list[_Field]]
    lock: dict[str, Any]
    versions: dict[str, str]


def _read(root: Path) -> _Metadata:
    try:
        root = Path(root).resolve(strict=True)
        originals, modes = {}, {}
        for relative in _PATHS:
            path = _path(root, relative)
            if not path.is_file():
                raise ValueError(f"{relative}: expected a regular metadata file")
            originals[relative] = path.read_bytes()
            modes[relative] = stat.S_IMODE(path.stat().st_mode)
        texts = {relative: value.decode("utf-8") for relative, value in originals.items()}
        fields = {relative: _project(texts[relative], name, relative) for relative, name in _PROJECTS.items()}
        current = {name: fields[relative][0].value for relative, name in _PROJECTS.items()}
        fields.update({relative: _init(texts[relative], name, relative) for relative, name in _INITS.items()})
        fields.update({relative: _lock(texts[relative], packages, relative) for relative, packages in _LOCKS.items()})
        lock = _manifest(root, texts[components.LOCK_FILE])
        recorded = lock["components"]["soota"]["version"]
        recorded = _LEGACY_SOOTA.split("+")[0] if recorded == _LEGACY_SOOTA else _version(recorded, "soota.version")
        comparisons = [(relative, field.name, field.value) for relative, items in fields.items() for field in items]
        comparisons.extend(
            [
                (f"{components.LOCK_FILE}: product.version", "lorelab", lock["product"]["version"]),
                (f"{components.LOCK_FILE}: soota.version", "soota", recorded),
            ]
        )
        for label, name, actual in comparisons:
            if actual != current[name]:
                raise ValueError(f"{label}: {name} version mismatch: {actual!r}, expected {current[name]!r}")
        return _Metadata(root, originals, modes, fields, lock, current)
    except OSError as exc:
        raise RuntimeError(f"Cannot read release metadata: {exc}") from exc


def versions(root: Path) -> dict[str, str]:
    """核对七份元数据的版本一致性；组件源码或 Skill 尚未 refresh 不影响读取。"""
    return _read(root).versions


def _render(metadata: _Metadata, target: dict[str, str]) -> dict[str, bytes]:
    result = dict(metadata.originals)
    for relative, fields in metadata.fields.items():
        original = metadata.originals[relative].decode("utf-8")
        text = original
        for field in sorted(fields, key=lambda item: item.start, reverse=True):
            text = text[: field.start] + target[field.name] + text[field.end :]
        if relative in _PROJECTS or relative in _LOCKS:
            # 回读候选 TOML，只允许目标包的版本字段改变，依赖和解析结果保持原样。
            expected = tomllib.loads(original)
            if relative in _PROJECTS:
                expected["project"]["version"] = target[_PROJECTS[relative]]
            else:
                for package in expected["package"]:
                    if package["name"] in _LOCKS[relative]:
                        package["version"] = target[package["name"]]
            if tomllib.loads(text) != expected:
                raise ValueError(f"{relative}: version edit would change unrelated metadata")
        result[relative] = text.encode("utf-8")
    lock = copy.deepcopy(metadata.lock)
    lock["product"]["version"] = target["lorelab"]
    soota = lock["components"]["soota"]
    if soota["version"] == _LEGACY_SOOTA:
        soota.setdefault("import_version", soota["version"])
    soota["version"] = target["soota"]
    if lock != metadata.lock:
        result[components.LOCK_FILE] = (json.dumps(lock, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return result


def _write(path: Path, content: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _rollback(metadata: _Metadata, touched: list[str]) -> list[str]:
    errors = []
    for relative in reversed(touched):
        try:
            path = _path(metadata.root, relative)
            original = metadata.originals[relative]
            if not path.exists() or path.read_bytes() != original:
                _write(path, original, metadata.modes[relative])
        except Exception as exc:  # noqa: BLE001 - 继续恢复其他文件，并汇总全部恢复失败。
            errors.append(f"{relative}: {exc}")
    return errors


def prepare(root: Path, product_version: str, soota_version: str) -> dict[str, Any]:
    """同步版本并刷新指纹；异常时仅恢复本轮触及的七份元数据。

    报告包含 before/after 版本、实际字节变化的 changed_paths 和最终 components 验收。
    """
    target = {
        "lorelab": _version(product_version, "product_version"),
        "soota": _version(soota_version, "soota_version"),
    }
    metadata = _read(root)
    for name, version in target.items():
        if tuple(map(int, version.split("."))) < tuple(map(int, metadata.versions[name].split("."))):
            raise ValueError(f"{name}: version downgrade from {metadata.versions[name]} to {version} is not allowed")
    # 先核对结构与源码可读性，允许正常开发中尚未刷新的旧指纹。
    inspection, _ = components._inspect(metadata.root, metadata.lock, compare=False)
    if not inspection["ok"]:
        raise ValueError("Invalid component metadata: " + "; ".join(inspection["errors"]))
    rendered = _render(metadata, target)
    touched: list[str] = []
    try:
        for relative, original in metadata.originals.items():
            if _path(metadata.root, relative).read_bytes() != original:
                raise RuntimeError(f"{relative}: metadata changed during preparation")
        for relative, content in rendered.items():
            if content != metadata.originals[relative]:
                touched.append(relative)
                _write(_path(metadata.root, relative), content, metadata.modes[relative])
        if components.LOCK_FILE not in touched:
            touched.append(components.LOCK_FILE)
        refreshed = components.refresh(metadata.root)
        if not refreshed["ok"]:
            raise RuntimeError("Component refresh failed: " + "; ".join(refreshed["errors"]))
        if versions(metadata.root) != target:
            raise RuntimeError("Prepared versions do not match the requested versions")
        verified = components.verify(metadata.root)
        if not verified["ok"]:
            raise RuntimeError("Component verification failed: " + "; ".join(verified["errors"]))
        changed = [
            relative
            for relative, original in metadata.originals.items()
            if _path(metadata.root, relative).read_bytes() != original
        ]
        return {
            "ok": True,
            "before": metadata.versions,
            "after": target,
            "changed_paths": changed,
            "components": verified,
        }
    except Exception as exc:
        errors = _rollback(metadata, touched)
        if errors:
            raise RuntimeError(f"Version preparation failed ({exc}); rollback incomplete: {'; '.join(errors)}") from exc
        if isinstance(exc, (ValueError, RuntimeError)):
            raise
        raise RuntimeError(f"Version preparation failed; metadata restored: {exc}") from exc
