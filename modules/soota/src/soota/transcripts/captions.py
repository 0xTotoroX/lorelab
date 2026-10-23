from __future__ import annotations

import re
from typing import Any

from soota.errors import ContractError, InputError
from soota.models import (
    CaptionPayload,
    TranscriptDocument,
    TranscriptManifest,
    TranscriptSegment,
    TranscriptSource,
    TranscriptStatus,
)
from soota.transcripts.conversion import parse_payload

_CLOCK = re.compile(r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})")


def parse_transcript_markdown(text: str, manifest: TranscriptManifest) -> TranscriptDocument:
    # Generated files frame each verbatim body with an anchor and fixed blank
    # lines. Remove that framing only, including for legacy second timestamps.
    pattern = re.compile(r'^## (seg-[^\s]+) · ([^\n]+)\n\n<a id="\1"></a>\n\n', re.M)
    matches = list(pattern.finditer(text))
    segments = []
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : next_start]
        body = body.removesuffix("\n\n" if index + 1 < len(matches) else "\n")
        segments.append(_saved_segment(match[1], match[2], body, manifest))
    if not matches:
        # Accept older/user-authored source files without generated anchors.
        headers = list(re.finditer(r"^## (seg-[^\s]+) · ([^\n]+)\n", text, re.M))
        for index, match in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            segments.append(_saved_segment(match[1], match[2], text[match.end() : end].strip(), manifest))
    return TranscriptDocument(
        status=manifest.status, source=manifest.source, language=manifest.language, segments=segments
    )


def _saved_segment(ident: str, timing: str, body: str, manifest: TranscriptManifest) -> TranscriptSegment:
    try:
        stamps = timing.split("-", 1) if timing != "无时间轴" else ["未知", "未知"]
        if len(stamps) != 2:
            raise ValueError("invalid time pair")
        stamps = [stamp.strip() for stamp in stamps]
        stamps = [stamp + ".000" if re.fullmatch(r"\d{2,}:\d{2}:\d{2}", stamp) else stamp for stamp in stamps]
        start, end = [None if stamp == "未知" else clock_to_ms(stamp) for stamp in stamps]
    except (ValueError, ContractError) as exc:
        raise InputError("源字幕时间轴无效，未处理正文。") from exc
    return TranscriptSegment(
        segment_id=ident,
        start_ms=start,
        end_ms=end,
        text=body,
        language=manifest.language,
        source=manifest.source or TranscriptSource.UNKNOWN,
    )


def clock_to_ms(value: str) -> int:
    match = _CLOCK.fullmatch(value.strip())
    if not match:
        raise ContractError(f"无法解析时间戳: {value}", hint="字幕时间轴格式已漂移。")
    hours, minutes, seconds, millis = (int(p) for p in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def ms_to_clock(ms: int) -> str:
    ms = max(0, int(ms))
    seconds, milli = divmod(ms, 1000)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def assign_ids(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    out: list[TranscriptSegment] = []
    for index, segment in enumerate(segments, start=1):
        out.append(segment.model_copy(update={"segment_id": f"seg-{index:06d}"}))
    return out


def parse_srt(text: str, *, language: str | None, source: TranscriptSource) -> list[TranscriptSegment]:
    return parse_payload(CaptionPayload(format="srt", body=text), language=language, source=source)


def parse_json3(payload: Any, *, language: str | None, source: TranscriptSource) -> list[TranscriptSegment]:
    return parse_payload(CaptionPayload(format="json3", body=payload), language=language, source=source)


def parse_bilibili_body(payload: Any, *, language: str | None, source: TranscriptSource) -> list[TranscriptSegment]:
    return parse_payload(CaptionPayload(format="bilibili-json", body=payload), language=language, source=source)


def empty_caption_result() -> dict[str, Any]:
    return {"status": TranscriptStatus.MISSING.value, "tracks": [], "segments": []}


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x2CEAF


def _join_parts(parts: list[str]) -> str:
    out = parts[0]
    for part in parts[1:]:
        if not part:
            continue
        if not out:
            out = part
            continue
        if out[-1].isspace() or part[0].isspace():
            out += part
        elif _is_cjk(out[-1]) or _is_cjk(part[0]):
            out += part
        else:
            out += " " + part
    return out.strip()


def merge_paragraphs(
    segments: list[TranscriptSegment],
    *,
    gap_ms: int = 1200,
    max_chars: int = 220,
) -> list[str]:
    """Merge timed cue text into readable paragraphs. Timestamps stay on transcript.md."""
    paras: list[str] = []
    buf: list[str] = []
    prev_end: int | None = None
    sentence_end = ("。", "！", "？", "；", ".", "!", "?")
    for segment in segments:
        piece = segment.text.strip()
        if not piece:
            continue
        gap = 0 if prev_end is None or segment.start_ms is None else segment.start_ms - prev_end
        current = _join_parts(buf) if buf else ""
        should_break = bool(buf) and (gap >= gap_ms or current.endswith(sentence_end) or len(current) >= max_chars)
        if should_break:
            paras.append(current)
            buf = [piece]
        else:
            buf.append(piece)
        prev_end = segment.end_ms
    if buf:
        paras.append(_join_parts(buf))
    return paras
