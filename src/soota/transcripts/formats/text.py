from __future__ import annotations

import csv
import io
import re

import webvtt

from soota.errors import ContractError
from soota.transcripts.formats.common import Cue, clock, milliseconds, plain_markup


def normalized(text: str) -> str:
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n[ \t]*\n", normalized(text).strip("\n")):
        lines = block.split("\n")
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines or not block.strip():
            continue
        match = re.fullmatch(r"\s*(\S+)\s*-->\s*(\S+)(?:\s+.*)?", lines[0])
        if not match or len(lines) < 2:
            raise ContractError("SRT 字幕块缺少有效时间轴或正文。")
        cues.append(Cue(clock(match[1]), clock(match[2]), plain_markup("\n".join(lines[1:]))))
    return cues


def vtt(text: str) -> list[Cue]:
    text = normalized(text)
    if not re.match(r"\AWEBVTT(?:[ \t].*)?(?:\n|$)", text):
        raise ContractError("VTT 缺少 WEBVTT 文件头。")
    # webvtt-py ignores malformed blocks. Verify each cue boundary first so a
    # partial parse cannot masquerade as complete source text.
    timings = []
    for block in re.split(r"\n[ \t]*\n", text.strip())[1:]:
        lines = block.split("\n")
        if re.match(r"^(?:NOTE(?:\s|$)|STYLE$|REGION$)", lines[0]):
            continue
        index = 0 if "-->" in lines[0] else 1
        if index >= len(lines) or len(lines) <= index + 1:
            raise ContractError("VTT 字幕块缺少时间轴或正文。")
        match = re.fullmatch(r"\s*(\S+)\s+-->\s+(\S+)(?:\s+.*)?", lines[index])
        if not match:
            raise ContractError("VTT 字幕时间轴无效。")
        if any("-->" in line for line in lines[index + 1 :]):
            raise ContractError("VTT 字幕块缺少分隔空行或含额外时间轴。")
        timings.append((clock(match[1]), clock(match[2])))
    parsed = list(webvtt.from_string(text))
    if len(parsed) != len(timings):
        raise ContractError("VTT 解析未覆盖全部字幕块。")
    return [Cue(start, end, plain_markup(cue.raw_text)) for (start, end), cue in zip(timings, parsed, strict=True)]


def tsv(text: str) -> list[Cue]:
    rows = csv.DictReader(io.StringIO(normalized(text)), delimiter="\t", quoting=csv.QUOTE_NONE)
    if rows.fieldnames != ["start", "end", "text"]:
        raise ContractError("Whisper TSV 必须包含 start、end、text 三列（毫秒）。")
    cues = []
    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise ContractError("TSV 字幕列数不匹配。")
        cues.append(Cue(milliseconds(row["start"]), milliseconds(row["end"]), row["text"]))
    return cues


def txt(text: str) -> list[Cue]:
    # Plain text has no recoverable timeline. Do not invent zero timestamps.
    return [Cue(None, None, normalized(text))] if text.strip() else []
