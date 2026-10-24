"""[INPUT]: 来源目标和用户明确要求的语义、交付目标。
[OUTPUT]: LoreLab 内容任务；可投影为纯 Soota 采集请求。
[POS]: 单来源工作流契约，旧任务字段保持兼容。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from soota.errors import InputError
from soota.tasks.models import OutputSpec, TaskSpec

SEMANTIC = {"analysis", "note", "article", "outline"}


def outputs(want, optional=None):
    names = [x.strip() for x in (want or "context").split(",") if x.strip()]
    extras = [x.strip() for x in (optional or "").split(",") if x.strip()]
    try:
        return [OutputSpec(kind=x, required=x not in extras) for x in dict.fromkeys([*names, *extras])]
    except ValidationError as exc:
        raise InputError("内容目标无效；支持来源产物和 analysis/note/article/outline。") from exc


class ContentTask(TaskSpec):
    owner: Literal["lorelab"] = "lorelab"

    def source_spec(self):
        targets = {x.kind: x.required for x in self.outputs if x.kind not in SEMANTIC}
        semantic = [x for x in self.outputs if x.kind in SEMANTIC]
        if semantic:
            targets["context"] = targets.get("context", False) or any(x.required for x in semantic)
        return TaskSpec.model_validate(
            {
                **self.model_dump(exclude={"owner"}),
                "outputs": [{"kind": k, "required": v} for k, v in targets.items()],
                "destination": None,
                "vault": None,
            }
        )


class KeyPoint(BaseModel):
    text: str
    evidence: list[str] = Field(default_factory=list)


class Chapter(BaseModel):
    title: str
    start_ms: int | None = None
    end_ms: int | None = None
    summary: str = ""


class Analysis(BaseModel):
    schema_version: int = 1
    summary: str
    key_points: list[KeyPoint] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    language: str | None = None
