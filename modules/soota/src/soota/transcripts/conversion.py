from __future__ import annotations

from decimal import InvalidOperation
from xml.etree.ElementTree import ParseError

from webvtt.errors import MalformedCaptionError, MalformedFileError

from soota.errors import ContractError
from soota.models import CaptionAcquisition, CaptionPayload, CaptionResult, TranscriptSegment, TranscriptSource
from soota.models import TranscriptStatus as Status
from soota.transcripts.formats import read_cues


def parse_payload(
    payload: CaptionPayload, *, language: str | None = None, source: TranscriptSource = TranscriptSource.UNKNOWN
) -> list[TranscriptSegment]:
    """The only raw-subtitle to normalized-segment boundary."""
    try:
        cues = read_cues(payload.format, payload.body)
        segments: list[TranscriptSegment] = []
        for cue in cues:
            if cue.start is not None and cue.end is not None and cue.end < cue.start:
                raise ContractError("字幕结束时间早于开始时间。")
            if cue.start is None and cue.end is not None:
                raise ContractError("字幕缺少开始时间。")
            if not cue.text.strip():
                continue
            segments.append(
                TranscriptSegment(
                    segment_id=f"seg-{len(segments) + 1:06d}",
                    start_ms=cue.start,
                    end_ms=cue.end,
                    text=cue.text,
                    language=language,
                    source=source,
                )
            )
        return segments
    except ContractError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        InvalidOperation,
        ParseError,
        MalformedCaptionError,
        MalformedFileError,
    ) as exc:
        raise ContractError(f"字幕不符合 {payload.format} 格式契约。") from exc


def convert_captions(acquired: CaptionAcquisition | CaptionResult) -> CaptionResult:
    # In-memory normalized results are used by selection and older integrations.
    # Providers themselves return CaptionAcquisition, including for old caches.
    if isinstance(acquired, CaptionResult):
        return acquired
    if acquired.status != Status.READY:
        return CaptionResult(
            status=acquired.status,
            reason=acquired.reason,
            source=acquired.source,
            language=acquired.language,
            tracks=acquired.tracks,
        )
    if acquired.payload is None:
        raise ContractError("字幕获取结果标记为 ready，但缺少原始正文。")
    segments = parse_payload(
        acquired.payload, language=acquired.language, source=acquired.source or TranscriptSource.UNKNOWN
    )
    if not segments:
        return CaptionResult(
            status=Status.UNKNOWN,
            reason="empty_caption_body",
            source=acquired.source,
            language=acquired.language,
            tracks=acquired.tracks,
        )
    return CaptionResult(
        status=Status.READY,
        segments=segments,
        source=acquired.source,
        language=acquired.language,
        tracks=acquired.tracks,
    )
