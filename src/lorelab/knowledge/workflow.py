"""[INPUT]: 显式收藏、目的地及可选分类体系、Agent 审阅与 runtime.run_json。
[OUTPUT]: 默认文章交付及显式大纲交付的持久化知识流程。
[POS]: LoreLab 知识交付编排；来源采集和跨来源文章任务分别保留恢复状态。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from . import library
from .workflow_cleanup import clean, reconcile_delete
from .workflow_publish import publish_approved, reconcile, writer
from .workflow_review import check_approved, submit_review, template
from .workflow_sources import check_sources, collect, handoffs, reread
from .workflow_state import (
    WorkflowError,
    default_root,
    destination,
    immutable,
    open_job,
    parts,
    read_json,
    require,
    save,
    seal,
    unseal,
    wants_outline,
    write_json,
)

__all__ = ["WorkflowError", "cleanup", "prepare", "publish", "status", "submit", "verify"]


def run_json(tool: str, args: list[str], receipt: Path | None = None, acceptable_codes: tuple = (0,)):
    # 延迟导入以允许独立 worktree 测试；测试只需 mock 此单一进程边界。
    from .runtime import run_json as invoke

    return invoke(tool, args, receipt=receipt, acceptable_codes=acceptable_codes)


def report(job: Path, state: dict) -> dict:
    sources = unseal(job, state, "sources.json") if "sources.json" in state.get("sealed", {}) else []
    bindings = unseal(job, state, "handoffs.json") if "handoffs.json" in state.get("sealed", {}) else {}
    spec = unseal(job, state, "spec.json")
    return {
        "ok": state["status"] not in {"prepare_failed", "publish_uncertain", "cleanup_uncertain"},
        **state,
        "delivery": "article-and-outline" if wants_outline(spec) else "article",
        "source_kind": spec.get("source_kind", "cubox"),
        "sources": sources,
        "handoffs": bindings,
        "review_template": str(job / "review-template.json"),
        **({"library": {"taxonomy": spec["library"], "paths": library.paths(spec["library"]),
                         "catalog_snapshot": str(job / "library-catalog.json"),
                         "note_fields": ["category", "related_categories (optional)"]}}
           if "library" in spec else {}),
        "retained_ids": [s["id"] for s in sources if s["id"] not in state.get("cleanup", {}).get("absent_ids", [])],
        "pending_source_ids": [s["id"] for s in sources if s["id"] not in bindings],
        "semantic_review": "完整原文、语义覆盖、目标规则与既有笔记须由 Agent 实读审阅；程序仅校验机械契约。",
    }


def prepare(
    ids_file: Path | None,
    vault: Path,
    subdir: str,
    mubu_doc: str | None = None,
    mubu_parent: str | None = None,
    delete_verified: bool = False,
    state_root: Path | None = None,
    mubu_auth: str = "desktop",
    source_bundles: dict[str, str] | None = None,
    with_outline: bool = False,
    cleanup_after: str = "article",
    bundles_file: Path | None = None,
) -> dict:
    vault = Path(vault).expanduser().resolve()
    require(vault.is_dir(), "vault 必须已存在。")
    parts(subdir)
    require(type(delete_verified) is bool and mubu_auth in {"desktop", "password"}, "删除授权或认证参数无效。")
    require(type(with_outline) is bool and cleanup_after in {"article", "outline"}, "交付或清理条件无效。")
    if with_outline:
        require(
            isinstance(mubu_doc, str) and bool(mubu_doc.strip()) and not mubu_doc.startswith("-"), "mubu_doc 无效。"
        )
    require(
        mubu_parent is None
        or isinstance(mubu_parent, str)
        and bool(mubu_parent.strip())
        and not mubu_parent.startswith("-"),
        "mubu_parent 无效。",
    )
    require((ids_file is None) != (bundles_file is None), "必须且只能选择 ids-file 或 bundles-file。")
    bundle_inputs = []
    if bundles_file is not None:
        from . import bundles

        require(not source_bundles, "bundles-file 与 Cubox 补抓映射不能同时使用。")
        bundle_inputs = bundles.inputs(Path(bundles_file))
        ids = bundles.identities(bundle_inputs)
        delete_verified = False  # 非收藏来源没有删除动作；不继承 Cubox 清理授权。
    else:
        ids = list(
            dict.fromkeys(x.strip() for x in Path(ids_file).read_text(encoding="utf-8-sig").splitlines() if x.strip())
        )
    require(
        ids and all("," not in x and not x.startswith("-") and not any(c.isspace() for c in x) for x in ids),
        "ids-file 必须每行一个 ID。",
    )
    supplied = {} if source_bundles is None else source_bundles
    require(
        isinstance(supplied, dict)
        and set(supplied) <= set(ids)
        and all(isinstance(v, str) and v for v in supplied.values()),
        "source_bundles 必须是本批 card_id 到包路径的映射。",
    )
    spec = {
        "kind": "batch",
        "with_outline": with_outline,
        "cleanup_after": cleanup_after,
        "vault": str(vault),
        "subdir": subdir,
        "destination": str(vault / subdir),
        "ids": ids,
        "mubu_doc": mubu_doc,
        "mubu_parent": mubu_parent,
        "mubu_auth": mubu_auth,
        "delete_verified": delete_verified,
        "source_bundles": supplied,
        "source_kind": "bundle" if bundle_inputs else "cubox",
        "bundle_inputs": [str(path) for path in bundle_inputs],
    }
    target = destination(spec)
    taxonomy = library.load(target)
    if taxonomy is not None:
        spec["library"] = taxonomy
    root = Path(state_root or default_root()).expanduser().resolve()
    require(not root.is_relative_to(vault) and not vault.is_relative_to(root), "状态目录必须与知识库分离。")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    job = root / uuid4().hex
    job.mkdir(mode=0o700)
    state = {"schema_version": 1, "job": str(job), "status": "preparing", "sealed": {}}
    seal(job, state, "spec.json", spec)
    if taxonomy is not None:
        seal(job, state, "library-catalog.json", library.catalog(target, taxonomy))
    immutable(job / "selected-ids.txt", ("\n".join(ids) + "\n").encode())
    save(job, state)
    with open_job(str(job)) as (job, state):
        try:
            if bundle_inputs:
                bundles.collect(job, state, bundle_inputs)
            else:
                collect(run_json, job, state, ids, supplied)
            save(job, state)
            handoffs(run_json, job, state)
            write_json(job / "review-template.json", template(job, state))
            state["status"] = "waiting_review"
            save(job, state)
        except Exception as exc:
            state["status"] = "prepare_failed"
            save(job, state)
            raise WorkflowError(f"prepare 未完成，已保留状态：{job}；{exc}") from exc
        return report(job, state)


def submit(job: str, review_file: Path) -> dict:
    with open_job(job) as (folder, state):
        submit_review(run_json, folder, state, Path(review_file))
        return report(folder, state)


def publish(job: str) -> dict:
    with open_job(job) as (folder, state):
        approved = check_approved(folder, state)
        deleted = set(state.get("cleanup", {}).get("ids", []))
        used = {s for n in approved["notes"] for s in n["source_ids"]} - deleted
        reread(run_json, folder, state, sorted(used), "publish-cards")
        publish_approved(run_json, folder, state)
        if state.get("cleanup"):
            reconcile_delete(run_json, folder, state)
        return report(folder, state)


def verify(job: str) -> dict:
    with open_job(job) as (folder, state):
        approved = check_approved(folder, state)
        deleted = set(state.get("cleanup", {}).get("ids", []))
        ids = [s["id"] for s in unseal(folder, state, "sources.json") if s["id"] not in deleted]
        reread(run_json, folder, state, ids, "verify-cards")
        with writer(unseal(folder, state, "spec.json")):
            require(reconcile(run_json, folder, state, approved), "交付尚未完整核对；幕布只能对账，不能重导入。")
            if state.get("cleanup"):
                reconcile_delete(run_json, folder, state)
        return report(folder, state)


def cleanup(job: str, execute: bool = False) -> dict:
    with open_job(job) as (folder, state):
        clean(run_json, folder, state, execute)
        return report(folder, state)


def status(job: str) -> dict:
    with open_job(job) as (folder, state):
        if "handoffs.json" in state.get("sealed", {}):
            check_sources(folder, state)
        if "approved.json" in state.get("sealed", {}):
            check_approved(folder, state)
            from .workflow_publish import inspect_notes

            inspect_notes(
                folder,
                state,
                read_json(folder / "approved.json"),
                require_saved=bool(state.get("notes") or state.get("mubu")),
            )
        return report(folder, state)
