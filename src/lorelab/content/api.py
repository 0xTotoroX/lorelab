"""[INPUT]: 采集参数、明确语义目标及旧任务入口。
[OUTPUT]: LoreLab 内容任务、派生文件及交付回执。
[POS]: 内容工作流 API；采集实现仅调用 Soota。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from pathlib import Path

from pydantic import ValidationError
from soota.errors import InputError
from soota.tasks.entry import prepare_task

from .legacy import write_bundle_to as write_legacy
from .models import SEMANTIC, ContentTask, outputs
from .render import render
from .tasks import execute, resume

__all__ = ["execute", "ingest", "render", "resume", "write_legacy"]


def ingest(settings, url=None, *, want=None, optional=None, destination=None, vault=None, subdir="Soota", **kwargs):
    requested = outputs(want, optional)
    source = {x.kind: x.required for x in requested if x.kind not in SEMANTIC}
    semantic = [x for x in requested if x.kind in SEMANTIC]
    if semantic:
        source["context"] = source.get("context", False) or any(x.required for x in semantic)
    spec = prepare_task(
        settings,
        url,
        want=",".join(source),
        optional=",".join(k for k, required in source.items() if not required),
        **kwargs,
    )
    try:
        task = ContentTask.model_validate(
            {
                **spec.model_dump(),
                "outputs": [x.model_dump() for x in requested],
                "destination": Path(destination).expanduser().resolve() if destination else None,
                "vault": Path(vault).expanduser().resolve() if vault else None,
                "subdir": subdir,
            }
        )
    except ValidationError as exc:
        raise InputError("内容任务参数无效；destination 与 vault 不能同时指定。") from exc
    return execute(
        settings.model_copy(update={"default_language": spec.language}), task, dry_run=kwargs.get("dry_run", False)
    )
