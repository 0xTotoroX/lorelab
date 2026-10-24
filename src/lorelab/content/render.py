"""[INPUT]: v1/v2 内容包和明确指定的分析提交。
[OUTPUT]: 版本适配后的派生输出及实际文件回执。
[POS]: LoreLab render API，旧 Soota render 只转发至此。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import json
from pathlib import Path

from soota.config import SootaSettings
from soota.errors import InputError
from soota.models import CommandResult, ContentBundleManifest, MediaItem
from soota.transcripts.captions import parse_transcript_markdown

from lorelab.content.load_analysis import load_analysis


def render(
    settings: SootaSettings,
    *,
    bundle: Path,
    analysis: Path,
    force: bool = False,
) -> CommandResult:
    manifest_path = bundle if bundle.name == "manifest.json" else bundle / "manifest.json"
    if not manifest_path.is_file():
        raise InputError("找不到 manifest.json。", hint="先 ingest 再 render。")
    folder = manifest_path.parent
    if json.loads(manifest_path.read_text(encoding="utf-8")).get("schema_version") == 2:
        from pydantic import ValidationError

        from lorelab.content.analysis import AnalysisSubmission, render_analysis

        try:
            submission = AnalysisSubmission.model_validate_json(analysis.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise InputError("v2 内容包需要带 context_fingerprint 的分析提交。") from exc
        updated = render_analysis(folder, submission, force=force)
        return CommandResult(
            ok=True,
            status="success",
            code="ok",
            exit_code=0,
            message="分析产物已写入，原文保持不变。",
            data={
                "output": str(folder),
                "manifest": str(manifest_path),
                "context": str(folder / "context.md"),
                "files": updated.files,
            },
        )
    parsed = load_analysis(analysis)
    manifest = ContentBundleManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    from lorelab.content.legacy import write_bundle_to

    meta = manifest.metadata or {}
    published = meta.get("published_at")
    published_at = None
    if isinstance(published, str) and published:
        from datetime import datetime

        published_at = datetime.fromisoformat(published)
    item = MediaItem(
        source=manifest.source,
        title=meta.get("title"),
        creator=meta.get("creator"),
        published_at=published_at,
        duration_seconds=meta.get("duration_seconds"),
        language=meta.get("language"),
    )
    document = parse_transcript_markdown((folder / "transcript.md").read_text(encoding="utf-8"), manifest.transcript)
    write_bundle_to(folder, item, document, manifest, parsed, force=force)
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message="已渲染 content.md。",
        data={
            "content": str(folder / "content.md"),
            "context": str(folder / "context.md") if (folder / "context.md").is_file() else None,
            "manifest": str(manifest_path),
        },
    )
