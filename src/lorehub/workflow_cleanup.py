"""[INPUT]: prepare 授权、冻结覆盖审阅、笔记与大纲实读结果。
[OUTPUT]: 清理预览、一次删除意图、active/archived 精确 URL 对账。
[POS]: 收藏删除门禁；未知结果与恢复只能读取。
"""

from pathlib import Path

from .workflow_publish import inspect_notes, reconcile, writer
from .workflow_review import check_approved
from .workflow_sources import folders, protected, reread
from .workflow_state import call, data, require, rows, save, unseal


def eligibility(job: Path, state: dict, approved: dict) -> list[str]:
    if unseal(job, state, "spec.json")["delete_verified"] is not True:
        return []
    sources = {s["id"]: s for s in unseal(job, state, "sources.json")}
    used = {s for n in approved["notes"] for s in n["source_ids"]}
    return [
        s["id"]
        for s in approved["sources"]
        if s["id"] in used
        and not sources[s["id"]]["protected"]
        and sources[s["id"]]["source_sha256"]
        and s["coverage"] == "complete"
        and s["all_valuable_parts_handled"] is True
        and s["gaps"] == []
    ]


def reconcile_delete(run, job: Path, state: dict):
    intent = state["cleanup"]
    sources = {s["id"]: s for s in unseal(job, state, "sources.json")}
    remaining = set()
    for index, url in enumerate(dict.fromkeys(sources[x]["url"] for x in intent["ids"])):
        require(isinstance(url, str) and url, "删除对账缺少原始 URL。")
        for archived in (False, True):
            args = ["card", "list", "--url", url, "--all", "-o", "json"]
            if archived:
                args.append("--archived")
            cards = rows(call(run, job, "cubox", args, f"cleanup-lookup-{index}-{int(archived)}"), "exactURL")
            require(all(isinstance(c.get("id"), str) for c in cards), "exactURL 返回无效 ID。")
            remaining.update(c["id"] for c in cards if c["id"] in intent["ids"])
    retained = [x for x in sources if x not in intent["ids"]]
    reread(run, job, state, retained, "cleanup-retained")
    check_approved(job, state)
    inspect_notes(job, state, unseal(job, state, "approved.json"), require_saved=True)
    intent.update(
        status="uncertain" if remaining else "verified",
        remaining_ids=sorted(remaining),
        absent_ids=[x for x in intent["ids"] if x not in remaining],
        retained_ids=retained,
        retained_unreadable_ids=[x for x in retained if sources[x]["status"] != "ok"],
    )
    state["status"] = "cleanup_uncertain" if remaining else "cleaned"
    save(job, state)


def clean(run, job: Path, state: dict, execute: bool):
    approved = check_approved(job, state)
    spec = unseal(job, state, "spec.json")
    require(type(execute) is bool, "execute 必须是布尔值。")
    if not spec["delete_verified"]:
        state["cleanup_preview"] = {"eligible_ids": [], "reason": "prepare 未明确授权删除。"}
        save(job, state)
        return
    with writer(spec):
        require(reconcile(run, job, state, approved), "知识/大纲尚未通过回读，不能清理。")
        if state.get("cleanup"):
            reconcile_delete(run, job, state)
            return
        ids = eligibility(job, state, approved)
        sources = unseal(job, state, "sources.json")
        retained = [s["id"] for s in sources if s["id"] not in ids]
        state["cleanup_preview"] = {"eligible_ids": ids, "retained_ids": retained, "executed": False}
        if not ids:
            save(job, state)
            return
        snapshot = {s["id"]: s for s in unseal(job, state, "cubox-snapshot.json")["items"]}
        listing = folders(run, job, "cleanup-folders")
        require(all(not protected(snapshot[x]["card"], listing) for x in ids), "来源现在属于 GitHub 保护范围。")
        all_ids = [s["id"] for s in sources]
        reread(run, job, state, all_ids, "cleanup-before")
        args = ["delete", "--id", ",".join(ids), "--keep-empty-tags", "-o", "json"]
        preview = data(call(run, job, "cubox", [*args, "--dry-run"], "cleanup-preview"))
        require(
            isinstance(preview, dict) and preview.get("dry_run") is True and preview.get("count") == len(ids),
            "Cubox dry-run 与预定删除范围不符。",
        )
        if preview.get("cards") is not None:
            require([c.get("id") for c in preview["cards"]] == ids, "Cubox dry-run ID 不符。")
        save(job, state)
        if not execute:
            return
        check_approved(job, state)
        require(reconcile(run, job, state, approved), "大纲回读失效。")
        reread(run, job, state, all_ids, "cleanup-final-cards")
        state["cleanup"] = {
            "status": "intent",
            "ids": ids,
            "retained_ids": retained,
            "approved_sha256": state["sealed"]["approved.json"],
        }
        state["status"] = "cleaning"
        save(job, state)
        try:
            call(run, job, "cubox", args, "cleanup-execute", (0, 1))
        except Exception:
            state["cleanup"]["status"] = "uncertain"
            state["status"] = "cleanup_uncertain"
            save(job, state)
            raise
        reconcile_delete(run, job, state)
