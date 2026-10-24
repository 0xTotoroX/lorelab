from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from pydantic import ValidationError

from soota.artifacts.analysis import AnalysisSubmission, render_analysis
from soota.artifacts.bundle import (
    content_from_markdown,
    load_bundle,
    load_transcript,
    save_bundle,
    verify_artifacts,
    write_artifact,
    write_bundle,
)
from soota.artifacts.models import BundleV2
from soota.billing import selected_provider
from soota.config import SootaSettings
from soota.errors import InputError, SootaError, SourceError
from soota.media import MediaDescriptor, MediaService
from soota.models import AnalysisStatus, MediaItem, TranscriptMode, TranscriptSource
from soota.storage.atomic import atomic_write
from soota.tasks.acquire import public_text
from soota.tasks.models import InputSpec, StepState, TaskItem, TaskJob, TaskSpec
from soota.tasks.state import (
    _bundle_lock,
    save_job,
)


def _export_subtitles(folder: Path, bundle: BundleV2, spec: TaskSpec) -> None:
    document = load_transcript(folder, bundle)
    if document is None or not document.segments:
        raise SourceError("没有可导出的字幕。")
    if spec.transcript_mode == TranscriptMode.CAPTIONS_ONLY and document.source == TranscriptSource.ASR:
        raise SourceError("本次要求原字幕；已有 ASR 结果不能冒充原字幕。")
    if (
        spec.strict_language
        and document.language
        and document.language.split("-")[0].lower() != spec.language.split("-")[0].lower()
    ):
        raise SourceError("已有字幕语言不满足本次指定语言。")
    from soota.transcripts.captions import ms_to_clock

    for format in spec.subtitle_formats:
        target = f"captions.{format}"
        if format in {"srt", "vtt"}:
            if any(s.start_ms is None or s.end_ms is None for s in document.segments):
                raise SourceError("字幕时间轴不完整，不能生成 SRT/VTT；可选择 txt/json。")
            parts = ["WEBVTT\n"] if format == "vtt" else []
            for index, segment in enumerate(document.segments, 1):
                assert segment.start_ms is not None and segment.end_ms is not None
                separator = "," if format == "srt" else "."
                start = f"{ms_to_clock(segment.start_ms)}{separator}{segment.start_ms % 1000:03d}"
                end = f"{ms_to_clock(segment.end_ms)}{separator}{segment.end_ms % 1000:03d}"
                parts.extend([str(index), f"{start} --> {end}", segment.text, ""])
            body = "\n".join(parts)
        elif format == "txt":
            body = "\n".join(s.text for s in document.segments) + "\n"
        else:
            body = document.model_dump_json(indent=2) + "\n"
        write_artifact(
            folder,
            bundle,
            path=target,
            kind="subtitle-export",
            format=format,
            content=body,
            provider=bundle.processing.provider,
            force=spec.force,
        )


def _handoff(folder: Path, bundle: BundleV2, spec: TaskSpec, job: TaskJob, row: TaskItem) -> None:
    if not bundle.context_fingerprint:
        raise SourceError("没有可供分析的正文，不能创建分析接续任务。")
    request = {
        "schema_version": 1,
        "task_id": job.id,
        "item_id": row.item_id,
        "context": str(folder / "context.md"),
        "context_fingerprint": bundle.context_fingerprint,
        "requested_outputs": sorted(spec.wants & {"note", "article", "analysis", "outline"}),
        "content_scope": bundle.content.scope if bundle.content else "transcript",
        "submission_schema": AnalysisSubmission.model_json_schema(),
        "instructions": "仅按本次明确目标生成分析或阅读文章；保留证据引用。导出到知识库时遵守目标目录约定。",
        "resume": f"soota jobs resume {job.id} --analysis <submission.json> --json",
    }
    atomic_write(folder / "analysis-request.json", json.dumps(request, ensure_ascii=False, indent=2) + "\n")
    if bundle.analysis.status != AnalysisStatus.READY:
        bundle.analysis.status = AnalysisStatus.PENDING
        save_bundle(folder, bundle)
    row.steps["analysis"] = StepState(status="waiting_analysis", artifacts=["analysis-request.json"])


def _images(
    settings: SootaSettings, spec: TaskSpec, seed: InputSpec, work: Path, folder: Path, bundle: BundleV2, row: TaskItem
) -> None:
    if bundle.content is None:
        raise SourceError("没有可供获取图片的正文。")
    references = work / "references.json"
    private = json.loads(references.read_text(encoding="utf-8")) if references.is_file() else {}
    raw_body = private.get("body", bundle.content.body_md)
    base = private.get("base", str(Path(seed.value).parent) if seed.kind == "file" else seed.value)
    matches = list(re.finditer(r"!\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)", raw_body))
    urls = list(dict.fromkeys(match[1] for match in matches))
    if not urls:
        raise SourceError("正文没有提供图片引用；未把空图集标为已交付。")
    service = MediaService(settings, work / "images", max_bytes=spec.max_bytes)
    failures = []
    body = raw_body
    for index, url in enumerate(urls, 1):
        try:
            if urlsplit(url).scheme in {"http", "https"} or urlsplit(base).scheme in {"http", "https"}:
                if spec.provider == "local":
                    raise InputError("local 模式不能获取远程图片。")
                selected_provider(settings, "http")
                absolute = urljoin(base, url)
                asset = service.from_descriptor(MediaDescriptor(url=absolute, source_provider="http"), kind="image")
            else:
                if urlsplit(url).scheme:
                    raise InputError("不支持正文中的本地文件 URL 协议。")
                original = (Path(base) / url).resolve()
                if seed.kind != "file" and not original.is_relative_to(
                    (folder if seed.kind == "bundle" else work).resolve()
                ):
                    raise InputError("工具正文引用了任务目录外的本地附件。")
                asset = service.from_file(original, kind="image")
            path = f"attachments/image-{index:03d}{asset.path.suffix}"
            write_artifact(
                folder,
                bundle,
                path=path,
                kind="image",
                format=asset.format,
                content=asset.path,
                provider=asset.source_provider,
                verification="media",
                attributes={
                    **asset.model_dump(mode="json", exclude={"path"}),
                    "acquisition_context": spec.execution_context,
                    "input_fingerprint": row.input_fingerprint,
                },
                force=spec.force,
            )
            body = body.replace(url, path)
        except (SootaError, OSError):
            failures.append(index)
    content = content_from_markdown(bundle.source, public_text(body), bundle.content.title, bundle.content.scope)
    item = MediaItem(
        source=bundle.source,
        title=bundle.metadata.get("title"),
        creator=bundle.metadata.get("creator"),
        provenance=bundle.metadata.get("provenance", {}),
    )
    updated = write_bundle(folder, item, content=content, force=spec.force)
    for artifact in updated.artifacts:
        if artifact.kind in {"body", "context", "transcript"}:
            artifact.attributes.update(
                acquisition_context=spec.execution_context,
                input_fingerprint=row.input_fingerprint,
                text_signature=spec.text_signature,
            )
    save_bundle(folder, updated)
    if failures:
        raise SourceError("部分图片未能保存，已保留其余产物。", details={"failed_image_indexes": failures})


def _apply_analysis(settings: SootaSettings, job: TaskJob, path: Path, *, force: bool) -> None:
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    for candidate in paths:
        try:
            submission = AnalysisSubmission.model_validate_json(candidate.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise InputError("分析提交不符合接续契约。") from exc
        if submission.task_id != job.id:
            raise InputError("分析提交的 task_id 不匹配。")
        item = next((row for row in job.items if row.item_id == submission.item_id), None)
        if item is None or item.bundle is None:
            raise InputError("分析提交的 item_id 不匹配。")
        folder = Path(item.bundle)
        with _bundle_lock(folder):
            previous = folder / "analysis.json"
            same = False
            if previous.is_file():
                try:
                    saved = AnalysisSubmission.model_validate_json(previous.read_text(encoding="utf-8"))
                    bundle = load_bundle(folder)
                    same = (
                        saved == submission
                        and not verify_artifacts(folder, bundle)
                        and bundle.context_fingerprint == submission.context_fingerprint
                    )
                except (ValueError, OSError):
                    same = False
            if not same:
                render_analysis(folder, submission, force=force)
        item.steps["analysis"] = StepState(status="completed", provider="agent")
        save_job(settings, job)
