from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, model_validator

from soota.artifacts.bundle import (
    _check_writable,
    bundle_folder,
    file_sha256,
    load_bundle,
    load_transcript,
    safe_path,
    write_artifact,
)
from soota.artifacts.models import BundleV2
from soota.errors import InputError
from soota.models import Analysis, AnalysisManifest, AnalysisStatus
from soota.render.bundle import STALE_WARNING


class AnalysisSubmission(BaseModel):
    context_fingerprint: str
    task_id: str | None = None
    item_id: str | None = None
    analysis: Analysis | None = None
    article_markdown: str | None = None
    note_markdown: str | None = None
    outline_markdown: str | None = None

    @model_validator(mode="after")
    def has_output(self) -> AnalysisSubmission:
        if self.analysis is None and not any((self.article_markdown, self.note_markdown, self.outline_markdown)):
            raise ValueError("分析提交没有任何产物。")
        return self


def _evidence(folder: Path, bundle: BundleV2) -> dict[str, str]:
    links: dict[str, str] = {}
    if bundle.content:
        links.update({block.block_id: f"context.md#{block.block_id}" for block in bundle.content.blocks})
    if bundle.transcript.path:
        document = load_transcript(folder, bundle)
        if document:
            links.update(
                {segment.segment_id: f"{bundle.transcript.path}#{segment.segment_id}" for segment in document.segments}
            )
    return links


def _render(analysis: Analysis, links: dict[str, str]) -> str:
    lines = ["# 分析", "", analysis.summary, ""]
    for point in analysis.key_points:
        evidence = " ".join(f"[{identity}]({links[identity]})" for identity in point.evidence)
        lines.extend([f"- {point.text}" + (f" {evidence}" if evidence else ""), ""])
    for chapter in analysis.chapters:
        lines.extend([f"## {chapter.title}", "", chapter.summary, ""])
    if analysis.tags:
        lines.extend(["标签：" + "、".join(analysis.tags), ""])
    return "\n".join(lines)


def render_analysis(folder: Path, submission: AnalysisSubmission, *, force: bool = False) -> BundleV2:
    from soota.artifacts.bundle import save_bundle

    folder = bundle_folder(folder)
    bundle = load_bundle(folder)
    source = safe_path(folder, "context.md" if (folder / "context.md").is_file() else "transcript.md")
    if not source.is_file() or not bundle.context_fingerprint:
        raise InputError("内容包没有可供分析的 context 或旧字幕。")
    actual = file_sha256(source)
    if submission.context_fingerprint != actual or bundle.context_fingerprint != actual:
        raise InputError("分析对应的 context 已变化，未写入过期结果。")
    links = _evidence(folder, bundle)
    referenced: set[str] = set()
    if submission.analysis:
        referenced.update(identity for point in submission.analysis.key_points for identity in point.evidence)
    bodies = [submission.article_markdown, submission.note_markdown, submission.outline_markdown]
    for body in bodies:
        if body:
            referenced.update(re.findall(r"(?:context|transcript)\.md#([A-Za-z0-9_-]+)", body))
            referenced.update(re.findall(r"\[((?:seg|para)-[A-Za-z0-9_-]+)\]", body))
    unknown = referenced - links.keys()
    if unknown:
        raise InputError("分析引用了不存在的证据：" + ", ".join(sorted(unknown)))
    outputs: dict[str, tuple[str, str]] = {}
    if submission.analysis:
        outputs["analysis.md"] = ("analysis", _render(submission.analysis, links))
    for name, kind, body in (
        ("content.md", "article", submission.article_markdown),
        ("note.md", "note", submission.note_markdown),
        ("outline.md", "outline", submission.outline_markdown),
    ):
        if body:
            outputs[name] = (kind, body)
    labels = {"analysis.md": "分析", "content.md": "阅读文章", "note.md": "笔记", "outline.md": "大纲"}
    for name, (kind, body) in list(outputs.items()):
        related = [f"[原文]({source.name})"]
        related.extend(f"[{labels[other]}]({other})" for other in outputs if other != name)
        outputs[name] = (kind, body.rstrip() + "\n\n" + " · ".join(related) + "\n")
    paths = [*outputs, "analysis.json"]
    for name in paths:
        # Even unmodified generated analysis requires explicit replacement authorization.
        if safe_path(folder, name).exists() and not force:
            raise InputError(f"分析产物已存在，未覆盖：{name}", hint="确认后显式使用 --force。")
        _check_writable(folder, bundle, name, force=force)
    for name, (kind, body) in outputs.items():
        write_artifact(
            folder,
            bundle,
            path=name,
            kind=kind,
            format="md",
            content=body,
            force=force,
            attributes={"context_fingerprint": actual},
        )
    write_artifact(
        folder,
        bundle,
        path="analysis.json",
        kind="analysis",
        format="json",
        content=submission.model_dump_json(indent=2) + "\n",
        force=force,
        attributes={"context_fingerprint": actual},
    )
    bundle.analysis = AnalysisManifest(status=AnalysisStatus.READY, path=next(iter(outputs)))
    bundle.processing.warnings = [warning for warning in bundle.processing.warnings if warning != STALE_WARNING]
    save_bundle(folder, bundle)
    return bundle
