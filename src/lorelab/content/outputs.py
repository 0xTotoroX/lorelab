"""[INPUT]: 来源指纹、任务身份及 Agent 提交。
[OUTPUT]: 冻结交接文件和通过核验的派生产物。
[POS]: 内容任务接续；保持旧交接字节与证据身份。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from soota.artifacts.bundle import (
    load_bundle,
    save_bundle,
    verify_artifacts,
)
from soota.artifacts.models import BundleV2
from soota.config import SootaSettings
from soota.errors import InputError, SourceError
from soota.models import AnalysisStatus
from soota.storage.atomic import atomic_write
from soota.tasks.models import StepState, TaskItem, TaskJob, TaskSpec
from soota.tasks.state import (
    _bundle_lock,
    save_job,
)

from lorelab.content.analysis import AnalysisSubmission, render_analysis


def _handoff(folder: Path, bundle: BundleV2, spec: TaskSpec, job: TaskJob, row: TaskItem) -> None:
    if not bundle.context_fingerprint:
        raise SourceError("没有可供分析的正文，不能创建分析接续任务。")
    request = {
        "schema_version": 1,
        "task_id": job.id,
        "item_id": row.item_id,
        "context": str(folder / "context.md"),
        "context_fingerprint": bundle.context_fingerprint,
        "requested_outputs": sorted(spec.wants & {"note", "article", "analysis", "outline"}),
        "content_scope": bundle.content.scope if bundle.content else "transcript",
        "submission_schema": AnalysisSubmission.model_json_schema(),
        "instructions": "仅按本次明确目标生成分析或阅读文章；保留证据引用。导出到知识库时遵守目标目录约定。",
        "resume": f"lorelab content resume {job.id} --analysis <submission.json> --json",
    }
    request_path = folder / "analysis-request.json"
    previous = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else None
    # 旧 knowledge 已冻结交接文件 hash。身份、正文和目标一致时逐字节保留。
    if previous is None or any(
        previous.get(k) != request[k] for k in ("task_id", "item_id", "context_fingerprint", "requested_outputs")
    ):
        atomic_write(request_path, json.dumps(request, ensure_ascii=False, indent=2) + "\n")
    if bundle.analysis.status != AnalysisStatus.READY:
        bundle.analysis.status = AnalysisStatus.PENDING
        save_bundle(folder, bundle)
    row.steps["analysis"] = StepState(status="waiting_analysis", artifacts=["analysis-request.json"])


def _apply_analysis(settings: SootaSettings, job: TaskJob, path: Path, *, force: bool) -> None:
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    for candidate in paths:
        try:
            submission = AnalysisSubmission.model_validate_json(candidate.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise InputError("分析提交不符合接续契约。") from exc
        if submission.task_id != job.id:
            raise InputError("分析提交的 task_id 不匹配。")
        item = next((row for row in job.items if row.item_id == submission.item_id), None)
        if item is None or item.bundle is None:
            raise InputError("分析提交的 item_id 不匹配。")
        folder = Path(item.bundle)
        with _bundle_lock(folder):
            previous = folder / "analysis.json"
            same = False
            if previous.is_file():
                try:
                    saved = AnalysisSubmission.model_validate_json(previous.read_text(encoding="utf-8"))
                    bundle = load_bundle(folder)
                    same = (
                        saved == submission
                        and not verify_artifacts(folder, bundle)
                        and bundle.context_fingerprint == submission.context_fingerprint
                    )
                except (ValueError, OSError):
                    same = False
            if not same:
                render_analysis(folder, submission, force=force)
        item.steps["analysis"] = StepState(status="completed", provider="agent")
        save_job(settings, job)
