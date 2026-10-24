"""[INPUT]: 明确提交的 Analysis 和来源证据。
[OUTPUT]: 带可追溯引用的派生 Markdown。
[POS]: 旧 v1 阅读输出，和 Soota 原文序列化分离。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

from soota.models import ContentBundleManifest, MediaItem, TranscriptDocument, TranscriptSegment
from soota.render.markdown import render_context
from soota.transcripts.captions import merge_paragraphs, ms_to_clock

from lorelab.content.models import Analysis


def evidence_link(segment: TranscriptSegment) -> str:
    link = f"[{segment.segment_id}](transcript.md#{segment.segment_id})"
    if segment.start_ms is None or segment.end_ms is None:
        return link
    return f"{link} · {ms_to_clock(segment.start_ms)}-{ms_to_clock(segment.end_ms)}"


def render_content(
    item: MediaItem,
    document: TranscriptDocument,
    manifest: ContentBundleManifest,
    analysis: Analysis | None,
) -> str:
    if analysis is None:
        return render_context(item, document)
    title = item.title or item.source.id
    lines = [
        f"# {title}",
        "",
        f"- 平台: {item.source.platform}",
        f"- 来源: [{item.source.canonical_url}]({item.source.canonical_url})",
        f"- 创作者: {item.creator or '-'}",
        f"- 发布: {item.published_at.isoformat() if item.published_at else '-'}",
        f"- 时长: {item.duration_seconds if item.duration_seconds is not None else '-'} 秒",
        (
            f"- 字幕: {document.source or document.status.value} / {document.language or '-'} / "
            f"{len(document.segments)} 段"
        ),
        "",
    ]
    lines.extend(["## 摘要", "", analysis.summary.strip() or "_空摘要_", ""])
    if analysis.key_points:
        lines.extend(["## 核心观点", ""])
        by_id = {seg.segment_id: seg for seg in document.segments}
        for index, point in enumerate(analysis.key_points, start=1):
            links = []
            for seg_id in point.evidence:
                segment = by_id.get(seg_id)
                if segment:
                    links.append(evidence_link(segment))
            suffix = "；".join(links)
            bullet = f"{index}. {point.text}"
            if suffix:
                bullet += f" ({suffix})"
            lines.append(bullet)
        lines.append("")
    if analysis.chapters:
        lines.extend(["## 章节", ""])
        for chapter in analysis.chapters:
            timing = ""
            if chapter.start_ms is not None and chapter.end_ms is not None:
                timing = f" · {ms_to_clock(chapter.start_ms)}-{ms_to_clock(chapter.end_ms)}"
            lines.append(f"### {chapter.title}{timing}")
            lines.append("")
            if chapter.summary:
                lines.append(chapter.summary)
                lines.append("")
    if analysis.tags:
        tags = " ".join(f"`{tag}`" for tag in analysis.tags)
        lines.extend(["## 标签", "", tags, ""])
    lines.extend(_body_section(document))
    lines.extend(["## 处理说明", ""])
    lines.extend(_processing(manifest, document))
    return "\n".join(lines) + "\n"


def _processing(manifest: ContentBundleManifest, document: TranscriptDocument) -> list[str]:
    return [
        f"- provider: {manifest.processing.provider}",
        f"- cache_hit: {str(manifest.processing.cache_hit).lower()}",
        f"- transcript_status: {document.status}",
        f"- estimated_cost_usd: {manifest.processing.estimated_cost_usd}",
        f"- request_count: {manifest.processing.request_count}",
        f"- price_basis: {manifest.processing.price_basis or '-'}",
        "",
    ]


def _body_section(document: TranscriptDocument) -> list[str]:
    paragraphs = merge_paragraphs(document.segments)
    if not paragraphs:
        return []
    lines = ["## 正文", ""]
    for para in paragraphs:
        lines.append(para)
        lines.append("")
    return lines
