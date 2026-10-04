from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from html import unescape
from xml.etree import ElementTree as ET

from soota.errors import ContractError
from soota.transcripts.formats.common import Cue, milliseconds


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attributes(node: ET.Element) -> dict[str, str]:
    return {local(key): value for key, value in node.attrib.items()}


def xml_text(node: ET.Element) -> str:
    parts = [node.text or ""]
    for child in node:
        tag = local(child.tag)
        if tag == "br":
            parts.append("\n")
        elif tag not in {"metadata", "head", "styling", "layout"}:
            parts.append(xml_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def read_root(text: str) -> ET.Element:
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
        raise ContractError("字幕 XML 不支持 DTD 或实体声明。")
    return ET.fromstring(text.removeprefix("\ufeff"))


def srv(root: ET.Element, format: str) -> list[Cue]:
    tag = local(root.tag)
    if tag == "transcript":
        actual, parent, cue_tag, start_key, dur_key, scale = "srv1", root, "text", "start", "dur", 1000
    elif tag == "timedtext":
        bodies = [node for node in root if local(node.tag) == "body"]
        if bodies:
            actual, parent, cue_tag, start_key, dur_key, scale = "srv3", bodies[0], "p", "t", "d", 1
        else:
            actual, parent, cue_tag, start_key, dur_key, scale = "srv2", root, "text", "t", "d", 1
    else:
        raise ContractError("XML 不是已支持的字幕结构；弹幕、HTML 和任意 XML 不作字幕处理。")
    if format not in {"xml", actual}:
        raise ContractError("声明的 SRV 格式与 XML 结构不一致。")
    cues = []
    for node in parent:
        tag = local(node.tag)
        if tag != cue_tag:
            if tag not in {"head", "w"}:
                raise ContractError("SRV 字幕包含未知正文节点。")
            continue
        text = xml_text(node)
        if actual == "srv1":
            text = unescape(text)
        if not text.strip():
            continue
        start = milliseconds(node.attrib[start_key], scale)
        end = start + milliseconds(node.attrib[dur_key], scale) if dur_key in node.attrib else None
        cues.append(Cue(start, end, text))
    return cues


@dataclass(frozen=True)
class MediaClock:
    fps: Fraction
    nominal_fps: int
    subframes: int
    ticks: Fraction

    @classmethod
    def from_root(cls, root: ET.Element) -> MediaClock:
        params = attributes(root)
        if params.get("timeBase", "media") != "media":
            raise ContractError("TTML 仅支持媒体时间轴，不支持 clock/smpte 时间基准。")
        rate = int(params.get("frameRate", "30"))
        subframes = int(params.get("subFrameRate", "1"))
        parts = params.get("frameRateMultiplier", "1 1").split()
        if len(parts) != 2 or rate <= 0 or subframes <= 0 or any(int(p) <= 0 for p in parts):
            raise ContractError("TTML 帧率参数无效。")
        fps = Fraction(rate) * Fraction(parts[0]) / Fraction(parts[1])
        ticks = Fraction(params.get("tickRate", str(fps * subframes if "frameRate" in params else 1)))
        if ticks <= 0:
            raise ContractError("TTML tickRate 必须为正数。")
        return cls(fps, rate, subframes, ticks)

    def time(self, value: str) -> Fraction:
        value = value.strip()
        offset = re.fullmatch(r"((?:\d+(?:\.\d+)?|\.\d+))(h|m|s|ms|f|t)", value)
        if offset:
            scale = {
                "h": Fraction(3600),
                "m": Fraction(60),
                "s": Fraction(1),
                "ms": Fraction(".001"),
                "f": 1 / self.fps,
                "t": 1 / self.ticks,
            }[offset[2]]
            return Fraction(offset[1]) * scale
        clock = re.fullmatch(r"(\d{2,}):(\d{2}):(\d{2})(?:(\.\d+)|:(\d{2,})(?:\.(\d+))?)?", value)
        if not clock or int(clock[2]) >= 60 or int(clock[3]) >= 60:
            raise ContractError("TTML 时间表达式无效。")
        seconds = Fraction(int(clock[1]) * 3600 + int(clock[2]) * 60 + int(clock[3]))
        if clock[4]:
            seconds += Fraction(clock[4])
        if clock[5]:
            frames, sub = int(clock[5]), int(clock[6] or 0)
            if frames >= self.nominal_fps or sub >= self.subframes:
                raise ContractError("TTML 帧或子帧超出帧率范围。")
            seconds += (Fraction(frames) + Fraction(sub) / self.subframes) / self.fps
        return seconds


def ttml(root: ET.Element) -> list[Cue]:
    clock = MediaClock.from_root(root)
    cues: list[Cue] = []

    def walk(node: ET.Element, parent_start: Fraction, parent_end: Fraction | None) -> Fraction | None:
        attrs = attributes(node)
        if attrs.get("timeContainer", "par") != "par":
            raise ContractError("TTML 顺序时间容器尚不支持；未按并行容器误读。")
        if any(key in attrs for key in ("repeatCount", "repeatDur", "speed", "autoReverse")):
            raise ContractError("TTML 动态重复时序不支持。")
        start = parent_start + clock.time(attrs.get("begin", "0s"))
        ends = [parent_end] if parent_end is not None else []
        if "end" in attrs:
            ends.append(parent_start + clock.time(attrs["end"]))
        if "dur" in attrs:
            ends.append(start + clock.time(attrs["dur"]))
        end = min(ends) if ends else None
        if end is not None and end < start:
            raise ContractError("TTML 字幕开始时间晚于结束时间。")
        tag = local(node.tag)
        if tag == "p":
            # A paragraph is the text unit. Reject dynamic inline timing until
            # it can be represented without duplicating or losing words.
            for descendant in node.iter():
                child_attrs = attributes(descendant)
                timed = any(
                    k in child_attrs
                    for k in ("begin", "end", "dur", "repeatCount", "repeatDur", "speed", "autoReverse")
                )
                if descendant is not node and (timed or child_attrs.get("timeContainer", "par") != "par"):
                    raise ContractError("TTML 段内动态时序尚不支持，未静默丢弃时间信息。")
            cues.append(Cue(int(start * 1000), int(end * 1000) if end is not None else None, xml_text(node)))
        else:
            for child in node:
                if local(child.tag) in {"body", "div", "p"}:
                    walk(child, start, end)
        return end

    walk(root, Fraction(0), None)
    return cues


def parse(text: str, format: str) -> list[Cue]:
    root = read_root(text)
    if local(root.tag) == "tt":
        if format not in {"ttml", "dfxp", "xml"}:
            raise ContractError("声明的字幕格式与 TTML 正文不一致。")
        return ttml(root)
    if format in {"ttml", "dfxp"}:
        raise ContractError("TTML 缺少 tt 根节点。")
    return srv(root, format)
