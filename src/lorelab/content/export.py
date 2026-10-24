"""[INPUT]: 已核验的内容包及显式目的地。
[OUTPUT]: 保护人工修改的目录交付与旧导出回执。
[POS]: LoreLab 内容交付；沿用 .soota-export.json 数据兼容。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from soota.artifacts.bundle import bundle_folder, file_sha256, load_bundle, safe_path, verify_artifacts
from soota.errors import InputError
from soota.storage.atomic import atomic_write

EXPORT_MANIFEST = ".soota-export.json"


def _target(bundle_path: Path, destination: Path | None, vault: Path | None, subdir: str) -> Path:
    if (destination is None) == (vault is None):
        raise InputError("导出须指定 destination 或 vault，且不能同时指定。")
    bundle = load_bundle(bundle_path)
    if vault is not None:
        if not vault.is_dir():
            raise InputError("显式指定的知识库目录不存在。")
        root = safe_path(vault, subdir)
    else:
        assert destination is not None
        root = destination
    identity = bundle.source.cache_identity
    slug = re.sub(r"[^\w.-]+", "-", bundle.source.id).strip(".-")[:60] or "item"
    platform = re.sub(r"[^\w-]+", "-", bundle.source.platform).strip("-") or "source"
    name = f"{slug}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
    return safe_path(root, f"{platform}/{name}")


def export_bundle(
    bundle_path: Path, *, destination: Path | None = None, vault: Path | None = None, subdir: str = "Soota"
) -> Path:
    folder = bundle_folder(bundle_path)
    bundle = load_bundle(folder)
    issues = verify_artifacts(folder, bundle)
    if issues:
        raise InputError("源内容包校验失败，未导出。", details={"artifacts": issues})
    target = _target(folder, destination, vault, subdir)
    if target.resolve() == folder.resolve():
        raise InputError("导出目标与原内容包相同。")
    record_path = safe_path(target, EXPORT_MANIFEST)
    previous: dict[str, Any] = {}
    if record_path.is_file():
        try:
            previous = json.loads(record_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise InputError("导出记录损坏，未覆盖目标文件。") from exc
        if not isinstance(previous, dict) or previous.get("source_identity") != bundle.source.cache_identity:
            raise InputError("导出目录属于不同来源，未覆盖。")
    managed = previous.get("managed_sha256", {})
    if not isinstance(managed, dict):
        raise InputError("导出记录缺少受管文件校验值。")
    names = [artifact.path for artifact in bundle.artifacts] + ["manifest.json"]
    digests: dict[str, str] = {}
    conflicts: list[str] = []
    for name in names:
        source = safe_path(folder, name)
        dest = safe_path(target, name)
        digests[name] = file_sha256(source)
        if dest.exists() and (not dest.is_file() or managed.get(name) != file_sha256(dest)):
            conflicts.append(name)
    if conflicts:
        raise InputError("导出目标存在未登记或已被人工修改的文件，未覆盖。", details={"conflicts": conflicts})
    # Preflight all collisions before writing; links remain relative because bundle layout is preserved.
    import shutil
    import tempfile

    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        source, dest = safe_path(folder, name), safe_path(target, name)
        if dest.is_file() and file_sha256(dest) == digests[name]:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".soota-export-", dir=dest.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, temporary)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
        try:
            if file_sha256(temporary_path) != digests[name]:
                raise InputError("源文件在导出期间变化，未替换对应目标。")
            temporary_path.replace(dest)
        finally:
            temporary_path.unlink(missing_ok=True)
    record = {
        "schema_version": 1,
        "source_identity": bundle.source.cache_identity,
        "managed_sha256": {**managed, **digests},
    }
    atomic_write(record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return target
