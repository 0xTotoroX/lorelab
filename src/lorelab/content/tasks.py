"""[INPUT]: LoreLab 内容请求、Soota 原文任务和 Agent 提交。
[OUTPUT]: 分析交接、派生产物、受保护导出及可恢复状态。
[POS]: 内容流程唯一编排；复用 Soota 采集执行器与原任务预算。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from contextlib import nullcontext
from pathlib import Path

from pydantic import ValidationError
from soota.artifacts.bundle import load_bundle
from soota.config import SootaSettings
from soota.errors import InputError, SootaError, SourceError
from soota.models import AnalysisStatus
from soota.storage.jobs import JobStore
from soota.tasks import runner as source
from soota.tasks.inputs import file_fingerprint
from soota.tasks.models import StepState, TaskJob
from soota.tasks.state import _bundle_lock, create_job, resolved_inputs, save_job, save_spec, task_folder

from .export import _target, export_bundle
from .models import SEMANTIC, ContentTask
from .outputs import _apply_analysis, _handoff


def _satisfied(folder, bundle, goal, spec, row):
    if goal in SEMANTIC:
        return (
            source._source_current(folder, bundle, spec.source_spec(), row)
            and bundle.analysis.status == AnalysisStatus.READY
            and any(a.format == "md" for a in source._valid(folder, bundle, goal))
        )
    return source._satisfied(folder, bundle, goal, spec.source_spec(), row)


def _finish_item(settings, spec, job, row):
    if row.bundle is None or row.status in {"blocked", "failed"}:
        return
    folder = Path(row.bundle)
    with _bundle_lock(folder):
        bundle = load_bundle(folder)
        if any(not _satisfied(folder, bundle, goal, spec, row) for goal in spec.wants & SEMANTIC):

            def request_analysis():
                if not source._source_current(folder, bundle, spec.source_spec(), row):
                    raise SourceError("尚未取得符合本次条件的正文，未创建分析接续。")
                _handoff(folder, bundle, spec, job, row)

            source._step(settings, job, row, "analysis-request", request_analysis)

        if spec.destination is not None or spec.vault is not None:

            def export():
                with job._export_lock:
                    target = _target(folder, spec.destination, spec.vault, spec.subdir)
                    if target.resolve() == folder.resolve():
                        raise InputError("导出目标与原内容包相同。")
                    with _bundle_lock(target):
                        return export_bundle(folder, destination=spec.destination, vault=spec.vault, subdir=spec.subdir)

            target = source._step(settings, job, row, "export", export)
            if target is not None:
                row.data["export"] = str(target)

        bundle = load_bundle(folder)
        missing = {goal for goal in spec.required if not _satisfied(folder, bundle, goal, spec, row)}
        missing.update(set(row.data.get("missing_outputs", [])) & spec.required)
        row.data.update(
            missing_outputs=sorted(missing), artifacts=[a.model_dump(mode="json") for a in bundle.artifacts]
        )
        if not missing and not any(e.get("step") == "export" for e in row.errors):
            row.status = "completed"
        elif missing <= SEMANTIC and row.steps.get("analysis", StepState()).status == "waiting_analysis":
            row.status = "waiting_analysis"
        else:
            row.status = "partial" if bundle.artifacts else "failed"
        save_job(settings, job, item=row)


def _status(job, spec):
    statuses = [row.status for row in job.items[: spec.max_items]]
    if not statuses:
        # Acquisition distinguishes an empty, completed enumeration from a failed one.
        return
    if all(x == "completed" for x in statuses):
        job.status = "completed"
    elif all(x in {"completed", "waiting_analysis"} for x in statuses):
        job.status = "waiting_analysis"
    elif any(x in {"completed", "partial", "waiting_analysis"} for x in statuses):
        job.status = "partial"
    else:
        job.status = "blocked" if "blocked" in statuses else "failed"
    if any(
        info.get("stop_reason") in {"budget_or_auth", "error", "storage", "interrupted"}
        for info in job.enumeration.values()
        if isinstance(info, dict)
    ):
        job.status = "partial"


def execute(settings: SootaSettings, spec, *, job=None, analysis=None, dry_run=False, _locked=False):
    spec = ContentTask.model_validate(spec.model_dump())
    if dry_run:
        from soota.models import CommandResult
        from soota.secrets import redact_any

        return CommandResult(
            ok=True,
            status="success",
            code="ok",
            exit_code=0,
            message="已生成 LoreLab 内容计划，未写入或联网。",
            data={"plan": redact_any(spec.model_dump(mode="json")), "network_discovery": "not_run"},
        )
    report = None
    if settings.updates.enabled and analysis is None and any(i.kind not in {"file", "bundle"} for i in spec.inputs):
        from soota.auto_updates import automatic_update

        report = automatic_update(settings)
    job = job or create_job(settings, spec)
    guard = nullcontext() if _locked else JobStore(settings.jobs_dir).lock(job.id)
    with guard:
        try:
            if analysis is not None:
                # 不将过期本地来源的旧分析写入包；原任务身份与费用仍沿用。
                inputs = resolved_inputs(settings, job)
                for row in job.items:
                    seed = inputs[row.input_index]
                    if seed.kind == "file" and file_fingerprint(Path(seed.value)) != row.input_fingerprint:
                        raise InputError("本地输入自任务创建后已变化，不能接收旧分析。")
                _apply_analysis(settings, job, Path(analysis), force=spec.force)
            source.execute(settings, spec.source_spec(), job=job, _locked=True)
            if job.status not in {"blocked", "failed", "paused"}:
                for row in job.items[: spec.max_items]:
                    _finish_item(settings, spec, job, row)
                _status(job, spec)
            save_job(settings, job)
        except KeyboardInterrupt:
            job.status = "paused"
            save_job(settings, job)
            raise
        except (SootaError, OSError) as exc:
            job.status = "blocked"
            job.warnings.append(source._error(exc)["message"])
            save_job(settings, job)
    result = source.result_for(settings, spec, job)
    if report:
        result.data["runtime_updates"] = report
        result.warnings.extend(report["warnings"])
    return result


def resume(
    settings,
    job_id,
    *,
    max_items=None,
    max_pages=None,
    max_cost=None,
    weir_max_credits=None,
    workers=None,
    analysis=None,
    force=False,
):
    store = JobStore(settings.jobs_dir)
    if store.get(job_id).get("kind") != "content-task":
        if analysis is not None:
            raise InputError("旧目录任务不接受分析提交。")
        return source.resume(
            settings,
            job_id,
            max_items=max_items,
            max_pages=max_pages,
            max_cost=max_cost,
            weir_max_credits=weir_max_credits,
            workers=workers,
            force=force,
        )
    with store.lock(job_id):
        job = TaskJob.model_validate(store.get(job_id))
        try:
            spec = ContentTask.model_validate_json(
                (task_folder(settings, job_id) / "request.json").read_text(encoding="utf-8")
            )
        except (ValueError, OSError) as exc:
            raise InputError("任务请求记录缺失或格式无效。") from exc
        updates = {
            key: value
            for key, value in {
                "max_items": max_items,
                "max_pages": max_pages,
                "max_cost": max_cost,
                "weir_max_credits": weir_max_credits,
                "workers": workers,
            }.items()
            if value is not None
        }
        incomplete = any(
            info.get("stop_reason")
            in {
                "budget_or_auth",
                "error",
                "storage",
                "interrupted",
                "max_pages",
                "max_items",
            }
            for info in job.enumeration.values()
            if isinstance(info, dict)
        )
        if job.enumeration and (updates.keys() - {"workers", "weir_max_credits"} or incomplete) and analysis is None:
            job.expanded = False
        from soota.tasks.entry import execution_context

        try:
            spec = ContentTask.model_validate(
                {
                    **spec.model_dump(),
                    **updates,
                    "force": force,
                    "execution_context": spec.execution_context
                    if analysis is not None
                    else execution_context(settings, spec.provider, spec.inputs, scope=spec.execution_scope),
                }
            )
        except ValidationError as exc:
            raise InputError("续跑参数无效；请检查范围和费用上限。") from exc
        save_spec(settings, job_id, spec)
        settings = settings.model_copy(update={"default_language": spec.language})
        return execute(settings, spec, job=job, analysis=analysis, _locked=True)
