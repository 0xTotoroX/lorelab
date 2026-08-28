from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from soota.errors import InputError
from soota.models import Analysis


def load_analysis(path: Path) -> Analysis:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError("Analysis JSON 无法解析。", hint=str(exc)) from exc
    try:
        return Analysis.model_validate(payload)
    except ValidationError as exc:
        raise InputError("Analysis 不符合 schema。", hint=str(exc)) from exc
