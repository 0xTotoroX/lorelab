from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import unescape

from soota.errors import ContractError


@dataclass(frozen=True)
class Cue:
    start: int | None
    end: int | None
    text: str


def milliseconds(value: object, scale: int = 1) -> int:
    if isinstance(value, bool):
        raise ContractError("字幕时间不能是布尔值。")
    try:
        number = Decimal(str(value)) * scale
        if not number.is_finite() or number < 0:
            raise ValueError("invalid time")
        return int(number)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ContractError("字幕时间必须是非负有限数值。") from exc


def clock(value: str) -> int:
    match = re.fullmatch(r"(?:(\d{2,}):)?(\d{2}):(\d{2})[.,](\d{3})", value)
    if not match or int(match[2]) >= 60 or int(match[3]) >= 60:
        raise ContractError("字幕时间轴格式无效。")
    return ((int(match[1] or 0) * 60 + int(match[2])) * 60 + int(match[3])) * 1000 + int(match[4])


def plain_markup(text: str) -> str:
    # Decode entities after removing *known* cue markup, so escaped literal
    # '<b>' remains text and mathematical comparisons are not swallowed.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:b|i|u|s|font|ruby|rt)(?:\s[^>]*)?>", "", text, flags=re.I)
    text = re.sub(r"</?(?:c|v|lang)(?:[.\s][^>]*)?>", "", text)
    text = re.sub(r"<(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}>", "", text)
    return unescape(text)
