from __future__ import annotations

import json
import re
from typing import Any

from soota.errors import ContractError
from soota.models import TranscriptSegment, TranscriptSource, TranscriptStatus

_SRT_BLOCK = re.compile(
    r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n(.*?)(?=\n\n|\Z)",
    re.S,
)
_CLOCK = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


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
    ordered = sorted(segments, key=lambda s: (s.start_ms, s.end_ms, s.text))
    out: list[TranscriptSegment] = []
    for index, segment in enumerate(ordered, start=1):
        out.append(segment.model_copy(update={"segment_id": f"seg-{index:06d}"}))
    return out


def parse_srt(
    text: str,
    *,
    language: str | None,
    source: TranscriptSource,
) -> list[TranscriptSegment]:
    blocks = _SRT_BLOCK.findall(text.replace("\r\n", "\n"))
    if not blocks and text.strip():
        raise ContractError("SRT 字幕无法按时间轴解析。", hint="上游字幕格式可能已变化。")
    segments: list[TranscriptSegment] = []
    for _, start, end, body in blocks:
        content = re.sub(r"<[^>]+>", "", body).replace("\n", " ").strip()
        if not content:
            continue
        segments.append(
            TranscriptSegment(
                segment_id="seg-tmp",
                start_ms=clock_to_ms(start),
                end_ms=clock_to_ms(end),
                text=content,
                language=language,
                source=source,
            )
        )
    return assign_ids(segments)


def parse_json3(
    payload: Any,
    *,
    language: str | None,
    source: TranscriptSource,
) -> list[TranscriptSegment]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict):
        raise ContractError("json3 字幕不是对象。")
    events = data.get("events")
    if not isinstance(events, list):
        raise ContractError("json3 字幕缺少 events。")
    segments: list[TranscriptSegment] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        segs = event.get("segs") or []
        text = "".join(str(part.get("utf8", "")) for part in segs if isinstance(part, dict)).strip()
        if not text or text == "\n":
            continue
        start = int(event.get("tStartMs") or 0)
        duration = int(event.get("dDurationMs") or 0)
        segments.append(
            TranscriptSegment(
                segment_id="seg-tmp",
                start_ms=start,
                end_ms=start + max(duration, 1),
                text=text.replace("\n", " "),
                language=language,
                source=source,
            )
        )
    if not segments:
        raise ContractError("json3 字幕没有可用文本片段。")
    return assign_ids(segments)


def parse_bilibili_body(
    payload: Any,
    *,
    language: str | None,
    source: TranscriptSource,
) -> list[TranscriptSegment]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict):
        raise ContractError("Bilibili 字幕 JSON 不是对象。")
    body = data.get("body")
    if not isinstance(body, list):
        raise ContractError("Bilibili 字幕缺少 body。", hint="不要把弹幕或评论当成字幕。")
    segments: list[TranscriptSegment] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        start = float(item.get("from") or 0) * 1000
        end = float(item.get("to") or 0) * 1000
        segments.append(
            TranscriptSegment(
                segment_id="seg-tmp",
                start_ms=int(start),
                end_ms=int(end if end > start else start + 1),
                text=text,
                language=language,
                source=source,
            )
        )
    if not segments:
        return []
    return assign_ids(segments)


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
        gap = 0 if prev_end is None else segment.start_ms - prev_end
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
