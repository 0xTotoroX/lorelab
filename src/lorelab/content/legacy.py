"""[INPUT]: 旧 v1 来源包、字幕与 Analysis。
[OUTPUT]: 保留原文的 content.md 渲染。
[POS]: 旧数据适配，仅 LoreLab 执行派生写入。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import json
from pathlib import Path

from soota.errors import InputError
from soota.models import (
    AnalysisManifest,
    AnalysisStatus,
    ContentBundleManifest,
    MediaItem,
    TranscriptDocument,
)
from soota.render.bundle import STALE_WARNING
from soota.render.bundle import write_bundle_to as write_source
from soota.storage.atomic import atomic_write

from lorelab.content.markdown import render_content
from lorelab.content.models import Analysis


def write_bundle_to(
    folder: Path,
    item: MediaItem,
    document: TranscriptDocument,
    manifest: ContentBundleManifest,
    analysis: Analysis,
    *,
    force: bool = False,
) -> Path:
    manifest_path = folder / "manifest.json"
    previous = (
        ContentBundleManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else None
    )
    if previous and previous.source.cache_identity != item.source.cache_identity:
        raise InputError("已有内容包属于不同来源，未覆盖文件。")
    content_path = folder / "content.md"
    if content_path.exists() and not force:
        raise InputError(
            "阅读或分析文件 content.md 已存在，未覆盖。", hint="确认替换后显式使用 lorelab content render --force。"
        )
    if previous is None:
        if (folder / "context.md").exists() or (folder / "transcript.md").exists():
            raise InputError("目录中有未登记的源文件；请先采集内容包或使用新的输出目录。")
        write_source(folder, item, document, manifest)
    else:
        manifest.files = {**previous.files, **manifest.files}
    manifest.processing.warnings = [w for w in manifest.processing.warnings if w != STALE_WARNING]
    atomic_write(content_path, render_content(item, document, manifest, analysis))
    manifest.analysis = AnalysisManifest(status=AnalysisStatus.READY, path="content.md")
    manifest.files.update({"content.md": "content.md", "manifest.json": "manifest.json"})
    atomic_write(manifest_path, json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
    return folder
