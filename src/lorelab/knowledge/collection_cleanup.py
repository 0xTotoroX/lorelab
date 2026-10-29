"""[INPUT]: collection 全批审阅、真实交付、固定 X 收藏及失效/无新知识的单独删除授权。
[OUTPUT]: dry-run、持久删除意图、active/archived 只读对账；无网址的文本收藏留在快照中。
[POS]: collection 清理门禁；复用 workflow 的 CLI 回执、保护检查与状态锁。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from . import collection as c
from . import runtime
from .workflow_publish import writer
from .workflow_sources import batch, folders, protected
from .workflow_state import call, data, digest, encoded, read_json, require, rows, save, seal, unseal


def validate_authorization(value, selected, sources):
    require(isinstance(value, dict) and value.get("schema_version") == 1, "删除授权版本无效。")
    c.text(value.get("reason"), "用户明确删除授权的理由/范围")
    for field in ("delete_ids", "unavailable_ids", "no_yield_ids"):
        ids = value.get(field, []) if field == "no_yield_ids" else value.get(field)
        require(isinstance(ids, list) and all(isinstance(x, str) for x in ids) and len(set(ids)) == len(ids),
                "删除授权必须是无重复的明确 ID 数组。")
    ids, unavailable = value["delete_ids"], value["unavailable_ids"]
    require(ids and set(ids) <= set(sources) and set(ids) <= set(selected), "删除目标为空、越界或尚未审阅。")
    expected = {key for key in ids if selected[key]["decision"] == "confirmed-unavailable"}
    require(set(unavailable) == expected, "失效来源必须有单独且精确的 unavailable_ids 删除授权。")
    expected_no_yield = {key for key in ids if selected[key]["decision"] == "reviewed-no-yield"}
    require(set(value.get("no_yield_ids", [])) == expected_no_yield,
            "无新知识来源必须有单独且精确的 no_yield_ids 删除授权。")
    require(all(selected[key]["decision"] in {"processed", "confirmed-unavailable", "reviewed-no-yield"} for key in ids),
            "retain/缺失来源必须保留。")
    return ids


def authorize(job, file):
    value = read_json(file)
    with c.opened(job) as (folder, state, _spec):
        c.mutable(state)
        sources = {s["id"]: s for s in unseal(folder, state, "sources.json")}
        validate_authorization(value, c.reviews(folder, state), sources)
        name = f"authorizations/{digest(encoded(value))}.json"
        seal(folder, state, name, value)
        state["authorization"] = name
        state.pop("cleanup_preview", None)
        save(folder, state)
        return c.report(folder, state)


def inventory(run, job, name):
    """读取完整元数据；文本收藏可无 URL，目标 X/仓库身份由调用方逐项核对。"""
    cards = {}
    for archived in (False, True):
        args = ["card", "list", "--all", "-o", "json"]
        if archived:
            args.append("--archived")
        values = rows(call(run, job, "cubox", args, f"{name}-{int(archived)}"), "完整收藏列表")
        for value in values:
            key = value.get("id")
            require(isinstance(key, str) and key.isdigit(), "收藏快照缺少真实 ID。")
            require(key not in cards, "收藏快照存在重复 ID；状态可能在分页期间改变。")
            require(value.get("url") is None or isinstance(value["url"], str), "收藏快照 URL 类型无效。")
            require("folder" in value and (value["folder"] is None or isinstance(value["folder"], dict)),
                    "收藏快照缺少文件夹信息，无法核实保护范围。")
            cards[key] = value
    return cards


def live_sources(run, job, sources, ids, name):
    if not ids:
        return {}
    if len(ids) > 100:
        snapshot = inventory(run, job, name)
        require(set(ids) <= snapshot.keys(), "X 收藏无法实际回读，停止清理。")
        for key in ids:
            c.x_status(snapshot[key].get("url"), sources[key]["status_id"])
        return {key: snapshot[key] for key in ids}
    cards = {}
    for offset in range(0, len(ids), 100):
        result = batch(run, job, ids[offset:offset + 100], f"{name}-{offset}")
        for item in result["items"]:
            require(item["status"] == "ok", "X 收藏无法实际回读，停止清理。")
            c.x_status(item["card"].get("url"), sources[item["id"]]["status_id"])
            cards[item["id"]] = item["card"]
    return cards


def reconcile(run, job, state, spec):
    intent = state["cleanup"]
    sources = {s["id"]: s for s in unseal(job, state, "sources.json")}
    remaining = set()
    # 未知写入只查询；即使删除回执失败或进程曾中断，也绝不重发。
    for archived in (False, True):
        args = ["card", "list", "--all", "-o", "json"]
        if archived:
            args.append("--archived")
        values = rows(call(run, job, "cubox", args, f"collection-lookup-{int(archived)}"), "完整收藏列表")
        require(all(isinstance(v.get("id"), str) for v in values), "删除回查缺少真实 ID。")
        require(len({v["id"] for v in values}) == len(values), "删除回查列表存在重复 ID。")
        remaining.update(v["id"] for v in values if v["id"] in intent["ids"])
    retained = [key for key in sources if key not in intent["ids"]]
    live_sources(run, job, sources, retained, "collection-retained")
    result = c.inspect(run, job, state, spec)
    require(result["ready"], "删除后交付核对失效。")
    intent.update(status="uncertain" if remaining else "verified", remaining_ids=sorted(remaining),
                  absent_ids=[key for key in intent["ids"] if key not in remaining], retained_ids=retained)
    state["status"] = "cleanup_uncertain" if remaining else "cleaned"
    save(job, state)


def cleanup(job, execute=False):
    require(type(execute) is bool, "execute 必须是布尔值。")
    with c.opened(job) as (folder, state, spec), writer(spec):
        if state.get("cleanup"):
            try:
                reconcile(runtime.run_json, folder, state, spec)
            except Exception:
                state["cleanup"]["status"] = "uncertain"
                state["status"] = "cleanup_uncertain"
                save(folder, state)
                raise
            return c.report(folder, state)
        require(state.get("authorization"), "未声明删除授权；默认保留全部来源。")
        sources = {s["id"]: s for s in unseal(folder, state, "sources.json")}
        authorization = unseal(folder, state, state["authorization"])
        ids = validate_authorization(authorization, c.reviews(folder, state), sources)
        require(c.inspect(runtime.run_json, folder, state, spec)["ready"], "全批仍有未读/未处理来源，不能清理。")
        listing = folders(runtime.run_json, folder, "collection-cleanup-folders")
        cards = live_sources(runtime.run_json, folder, sources, list(sources), "collection-cleanup-before")
        require(all(not protected(cards[key], listing) for key in ids), "GitHub 卡片或保护目录中的收藏不能删除。")
        args = ["delete", "--id", ",".join(ids), "--keep-empty-tags", "-o", "json"]
        preview = data(call(runtime.run_json, folder, "cubox", [*args, "--dry-run"], "collection-cleanup-preview"))
        require(isinstance(preview, dict) and preview.get("dry_run") is True and preview.get("count") == len(ids),
                "dry-run 与固定授权范围不符。")
        preview_cards = preview.get("cards")
        require(isinstance(preview_cards, list) and len(preview_cards) == len(ids)
                and all(isinstance(card, dict) and isinstance(card.get("id"), str) for card in preview_cards)
                and {card["id"] for card in preview_cards} == set(ids), "dry-run 必须返回精确删除 ID。")
        state["cleanup_preview"] = {"eligible_ids": ids, "retained_ids": [key for key in sources if key not in ids],
                                    "authorization_sha256": state["sealed"][state["authorization"]],
                                    "executed": False}
        save(folder, state)
        if not execute:
            return c.report(folder, state)
        # dry-run 后再次核对交付、来源身份和保护范围；随后 fsync 意图才派发一次删除。
        require(c.inspect(runtime.run_json, folder, state, spec)["ready"], "交付核对已失效。")
        listing = folders(runtime.run_json, folder, "collection-cleanup-final-folders")
        cards = live_sources(runtime.run_json, folder, sources, list(sources), "collection-cleanup-final")
        require(all(not protected(cards[key], listing) for key in ids), "来源已进入 GitHub 保护范围。")
        intent = {"ids": ids, "lookup_urls": list(dict.fromkeys(
            url for key in ids for url in (sources[key]["url"], cards[key]["url"]))),
            "authorization_sha256": state["sealed"][state["authorization"]],
            "review_sha256": state["ready"]["review_sha256"]}
        name = "cleanup-intent.json"
        seal(folder, state, name, intent)
        state["cleanup"] = {**intent, "status": "intent"}
        state["status"] = "cleaning"
        save(folder, state)
        try:
            call(runtime.run_json, folder, "cubox", args, "collection-cleanup-execute", (0, 1))
            reconcile(runtime.run_json, folder, state, spec)
        except Exception:
            state["cleanup"]["status"] = "uncertain"
            state["status"] = "cleanup_uncertain"
            save(folder, state)
            raise
        return c.report(folder, state)
