"""[INPUT]: 显式指定的旧 v1 Analysis JSON。
[OUTPUT]: 经过模型验证的语义提交。
[POS]: LoreLab 旧渲染入口的输入校验。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from soota.errors import InputError

from lorelab.content.models import Analysis


def load_analysis(path: Path) -> Analysis:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError("Analysis JSON 无法解析。", hint=str(exc)) from exc
    try:
        return Analysis.model_validate(payload)
    except ValidationError as exc:
        raise InputError("Analysis 不符合 schema。", hint=str(exc)) from exc
