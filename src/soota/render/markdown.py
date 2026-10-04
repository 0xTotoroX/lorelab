from __future__ import annotations

from soota.models import Analysis, ContentBundleManifest, MediaItem, TranscriptDocument, TranscriptSegment
from soota.transcripts.captions import merge_paragraphs, ms_to_clock


def evidence_link(segment: TranscriptSegment) -> str:
    return (
        f"[{segment.segment_id}](transcript.md#{segment.segment_id}) · "
        f"{ms_to_clock(segment.start_ms)}-{ms_to_clock(segment.end_ms)}"
    )


def render_context(item: MediaItem, document: TranscriptDocument) -> str:
    """Serialize source text in cue order without rewriting or merging it."""
    lines = [
        f"# {item.title or item.source.id}",
        "",
        f"source: {item.source.canonical_url}",
        f"transcript_status: {document.status.value}",
        f"transcript_source: {document.source.value if document.source else 'unknown'}",
        f"language: {document.language or 'unknown'}",
        "",
    ]
    lines.extend(f"[{segment.segment_id}] {segment.text}" for segment in document.segments)
    return "\n".join(lines) + "\n"


def _timestamp(ms: int) -> str:
    return f"{ms_to_clock(ms)}.{max(0, ms) % 1000:03d}"


def render_transcript(item: MediaItem, document: TranscriptDocument) -> str:
    title = item.title or item.source.id
    lines = [
        f"# {title} — 转写",
        "",
        f"- 来源: {document.source or document.status.value}",
        f"- 语言: {document.language or '-'}",
        f"- 片段: {len(document.segments)}",
        "",
    ]
    if not document.segments:
        lines.append("无可用字幕或转写。")
        lines.append("")
        return "\n".join(lines)
    for segment in document.segments:
        lines.extend(
            [
                f"## {segment.segment_id} · {_timestamp(segment.start_ms)}-{_timestamp(segment.end_ms)}",
                "",
                f'<a id="{segment.segment_id}"></a>',
                "",
                segment.text,
                "",
            ]
        )
    return "\n".join(lines)


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
        f"- 字幕: {document.source or document.status.value} / {document.language or '-'} / "
        f"{len(document.segments)} 段",
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
