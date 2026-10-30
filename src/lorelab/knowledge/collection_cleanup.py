"""[INPUT]: collection 全批审阅、真实交付、固定 X 收藏及失效/无新知识的单独删除授权。
[OUTPUT]: 授权、完整收藏快照及只读对账；分批执行交给 collection_cleanup_batches。
[POS]: collection 清理的共用校验；无网址的文本收藏保留，CLI 自动分页至空页。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from . import collection as c
from .workflow_sources import batch
from .workflow_state import call, digest, encoded, read_json, require, rows, save, seal, unseal


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
        args = ["card", "list", "--all", "--limit", "500", "-o", "json"]
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


def metadata(card):
    return {key: card.get(key) for key in
            ("title", "article_title", "description", "url", "domain", "read", "starred", "tags", "folder")}


def ensure_baseline(job, state, cards):
    name = "cleanup-baseline.json"
    if name not in state.get("sealed", {}):
        # 兼容曾完成试删但尚未保存基线的开发版本，优先采用第一批派发前的完整快照。
        batches = state.get("cleanup", {}).get("batches", [])
        if batches:
            prefix = batches[0]["receipt"].removesuffix("-execute.json")
            cards = {}
            for archived in (0, 1):
                for card in rows(read_json(job / f"{prefix}-before-{archived}.json"), "原批前快照"):
                    key = card.get("id")
                    require(isinstance(key, str) and key.isdigit() and key not in cards, "原批前快照 ID 无效。")
                    cards[key] = card
        seal(job, state, name, {key: metadata(card) for key, card in cards.items()})
        save(job, state)


def preservation(job, state, cards):
    name = "cleanup-baseline.json"
    if name not in state.get("sealed", {}):
        return  # 旧版本未保存基线时，不虚构历史保全证据。
    baseline = unseal(job, state, name)
    targets = set(state["cleanup"]["ids"])
    require(baseline.keys() - targets <= cards.keys(), "非删除目标有收藏缺失；保全问题尚未解决。")
    require(all(metadata(cards[key]) == original for key, original in baseline.items() if key in cards),
            "收藏人工元数据与清理基线不同；保全问题尚未解决。")


def reconcile(run, job, state, spec):
    intent = state["cleanup"]
    sources = {s["id"]: s for s in unseal(job, state, "sources.json")}
    # 未知写入只查询；即使删除回执失败或进程曾中断，也绝不重发。
    from uuid import uuid4

    cards = inventory(run, job, "collection-lookup-" + uuid4().hex)
    preservation(job, state, cards)
    remaining = set(intent["ids"]) & cards.keys()
    retained = [key for key in sources if key not in intent["ids"]]
    require(set(retained) <= cards.keys(), "保留来源缺失，停止清理。")
    for key in retained:
        c.x_status(cards[key].get("url"), sources[key]["status_id"])
    result = c.inspect(run, job, state, spec, cards=cards)
    require(result["ready"], "删除后交付核对失效。")
    paused = bool(remaining) and intent.get("status") == "paused"
    intent.update(status=("paused" if paused else "uncertain") if remaining else "verified", remaining_ids=sorted(remaining),
                  absent_ids=[key for key in intent["ids"] if key not in remaining], retained_ids=retained)
    state["status"] = ("cleanup_paused" if paused else "cleanup_uncertain") if remaining else "cleaned"
    state.pop("cleanup_error", None)
    save(job, state)


def cleanup(job, execute=False, *, batch_size=100, max_batches=None, resume=False):
    from .collection_cleanup_batches import cleanup as clean_batches

    return clean_batches(job, execute, batch_size=batch_size, max_batches=max_batches, resume=resume)
