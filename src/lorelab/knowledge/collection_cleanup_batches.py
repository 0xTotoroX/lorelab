"""[INPUT]: 冻结 collection 授权、真实交付、显式继续请求与 Cubox CLI。
[OUTPUT]: 有界分批删除、逐批持久意图和回读；失败停批，恢复只处理原名单仍存在项。
[POS]: collection 清理执行器；复用 collection_cleanup 的身份、保护和快照检查。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from datetime import UTC, datetime
from uuid import uuid4

from . import collection as c
from . import collection_cleanup as checks
from . import runtime
from .workflow_publish import writer
from .workflow_sources import folders, protected
from .workflow_state import call, data, require, save, seal, unseal


def _now():
    return datetime.now(UTC).isoformat()


def _preview(run, job, ids, name):
    args = ["delete", "--id", ",".join(ids), "--keep-empty-tags", "-o", "json"]
    value = data(call(run, job, "cubox", [*args, "--dry-run"], name))
    require(isinstance(value, dict) and value.get("dry_run") is True
            and type(value.get("count")) is int and value["count"] == len(ids),
            "dry-run 与固定授权范围不符。")
    cards = value.get("cards")
    require(isinstance(cards, list) and len(cards) == len(ids)
            and all(isinstance(v, dict) and isinstance(v.get("id"), str) for v in cards)
            and {v["id"] for v in cards} == set(ids), "dry-run 必须返回精确删除 ID。")
    return args


def _sources_and_outputs(run, job, state, spec, sources, ids, cards):
    retained = [key for key in sources if key not in ids]
    require(set(retained) <= cards.keys(), "保留来源缺失，停止清理。")
    for key in sources.keys() & cards.keys():
        c.x_status(cards[key].get("url"), sources[key]["status_id"])
    result = c.inspect(run, job, state, spec, cards=cards)
    require(result["ready"], "全批仍有未读/未处理来源，不能清理。")
    return retained


def _frozen(job, state, ids):
    intent = unseal(job, state, "cleanup-intent.json")
    require(intent["ids"] == ids and state["cleanup"]["ids"] == ids,
            "固定删除名单已改变，不能继续。")
    require(intent["authorization_sha256"] == state["sealed"][state["authorization"]],
            "原删除授权已改变，不能继续。")
    current = {key: state["sealed"][name] for key, name in state["reviews"].items()}
    require(intent["review_sha256"] == current, "冻结审阅已改变，不能继续。")


def _totals(job, state, sources, cards, *, uncertain=False):
    intent = state["cleanup"]
    pending = [key for key in intent["ids"] if key in cards]
    intent.update(remaining_ids=pending, absent_ids=[key for key in intent["ids"] if key not in cards],
                  retained_ids=[key for key in sources if key not in intent["ids"]], checked_at=_now())
    intent["status"] = "uncertain" if uncertain else ("paused" if pending else "verified")
    state["status"] = "cleanup_uncertain" if uncertain else ("cleanup_paused" if pending else "cleaned")
    if not uncertain:
        state.pop("cleanup_error", None)
    save(job, state)


def _metadata(card):
    # 不比较服务器可能自动更新的时间；人工可编辑的字段必须保全。
    return checks.metadata(card)


def _preserved(before, after, deleting):
    keep = before.keys() - set(deleting)
    require(keep <= after.keys(), "非本批删除目标有收藏缺失；停止后续批次。")
    changed = [key for key in keep if _metadata(before[key]) != _metadata(after[key])]
    require(not changed, "非本批删除目标的人工元数据已变化；停止后续批次。")


def _batch(run, job, state, spec, sources, ids, baseline, session, number):
    prefix = f"{session}/batch-{number:04d}"
    args = _preview(run, job, ids, prefix + "-preview")
    before = checks.inventory(run, job, prefix + "-before")
    _preserved(baseline, before, [])
    checks.preservation(job, state, before)
    listing = folders(run, job, prefix + "-folders")
    _sources_and_outputs(run, job, state, spec, sources, state["cleanup"]["ids"], before)
    _frozen(job, state, state["cleanup"]["ids"])
    require(set(ids) <= before.keys(), "本批目标在预览后变化；先对账再明确继续。")
    require(all(not protected(before[key], listing) for key in ids), "GitHub 卡片或保护目录中的收藏不能删除。")
    require(all(_metadata(before[key]) == _metadata(baseline[key]) for key in ids),
            "本批目标出现人工修改；停止删除并保留修改。")
    entry = {"ids": ids, "status": "intent", "created_at": _now(),
             "authorization_sha256": state["cleanup"]["authorization_sha256"],
             "original_intent_sha256": state["sealed"]["cleanup-intent.json"],
             "receipt": f"receipts/{prefix}-execute.json"}
    name = f"{prefix}-intent.json"
    seal(job, state, name, entry)
    state["cleanup"].setdefault("batches", []).append({**entry, "intent": name})
    batch_state = state["cleanup"]["batches"][-1]
    state["status"] = "cleaning"
    save(job, state)  # fsync 后才派发一次；进程中断不隐式重发。
    try:
        result = data(call(run, job, "cubox", args, prefix + "-execute"))
        receipt_ok = (isinstance(result, dict) and result.get("dry_run") is False
                      and type(result.get("count")) is int and result["count"] == len(ids))
        after = checks.inventory(run, job, prefix + "-after")
        _preserved(before, after, ids)
        checks.preservation(job, state, after)
        _sources_and_outputs(run, job, state, spec, sources, state["cleanup"]["ids"], after)
        verified = receipt_ok and not any(key in after for key in ids)
        _totals(job, state, sources, after, uncertain=not verified)
        batch_state.update(status="verified" if verified else "uncertain", receipt_valid=receipt_ok,
                           checked_at=_now(), remaining_ids=[key for key in ids if key in after])
        save(job, state)
        return after, batch_state["status"] == "verified"
    except Exception as exc:
        batch_state.update(status="uncertain", error_type=type(exc).__name__, stopped_at=_now())
        diagnostic = job / (entry["receipt"] + ".diagnostic.json")
        if diagnostic.is_file() and not diagnostic.is_symlink():
            batch_state["diagnostic"] = str(diagnostic.relative_to(job))
        state["cleanup"]["status"] = "uncertain"
        state["status"] = "cleanup_uncertain"
        save(job, state)
        # 错误回执/诊断保留原路径。失败后只读回查，即使查无也不继续下一批。
        try:
            after = checks.inventory(run, job, prefix + "-failed-lookup")
            batch_state["remaining_ids"] = [key for key in ids if key in after]
            _totals(job, state, sources, after, uncertain=True)
            _preserved(before, after, ids)
            checks.preservation(job, state, after)
            _sources_and_outputs(run, job, state, spec, sources, state["cleanup"]["ids"], after)
        except Exception as lookup_error:  # noqa: BLE001 - 保留原删除异常，不让回查异常掩盖它。
            batch_state["lookup_error_type"] = type(lookup_error).__name__
            save(job, state)
        raise


def cleanup(job, execute=False, *, batch_size=100, max_batches=None, resume=False):
    require(type(execute) is bool and type(resume) is bool, "execute/resume 必须是布尔值。")
    require(type(batch_size) is int and 1 <= batch_size <= 100, "batch_size 必须在 1–100 之间。")
    require(max_batches is None or type(max_batches) is int and max_batches > 0,
            "max_batches 必须是正整数。")
    require(not resume or execute, "--resume 必须与 --execute 一起明确使用。")
    with c.opened(job) as (folder, state, spec), writer(spec):
        try:
            return _run(folder, state, spec, execute, batch_size, max_batches, resume)
        except Exception as exc:
            # 删除已派发时保留 uncertain；派发前拒绝则明确 blocked，不能继续显示成功暂停。
            dispatched = state["status"] == "cleanup_uncertain"
            if not dispatched:
                state["status"] = "cleanup_blocked"
                if state.get("cleanup"):
                    state["cleanup"]["status"] = "blocked"
            state["cleanup_error"] = {"phase": "dispatch_or_readback" if dispatched else "preflight",
                                      "error_type": type(exc).__name__, "observed_at": _now()}
            save(folder, state)
            raise


def _run(folder, state, spec, execute, batch_size, max_batches, resume):
    if state.get("cleanup") and not resume:
        # 兼容旧命令：重复 --execute 仍只读，恢复必须显式 --resume。
        checks.reconcile(runtime.run_json, folder, state, spec)
        return c.report(folder, state)
    require(state.get("authorization"), "未声明删除授权；默认保留全部来源。")
    sources = {s["id"]: s for s in unseal(folder, state, "sources.json")}
    ids = checks.validate_authorization(unseal(folder, state, state["authorization"]),
                                        c.reviews(folder, state), sources)
    previous = bool(state.get("cleanup"))
    if previous:
        _frozen(folder, state, ids)
    session = f"cleanup-attempts/{uuid4().hex}"
    cards = checks.inventory(runtime.run_json, folder, session + "-initial")
    listing = folders(runtime.run_json, folder, session + "-folders")
    _sources_and_outputs(runtime.run_json, folder, state, spec, sources, ids, cards)
    pending = [key for key in ids if key in cards]
    require(previous or len(pending) == len(ids), "X 收藏无法实际回读，停止清理。")
    require(all(not protected(cards[key], listing) for key in pending),
            "GitHub 卡片或保护目录中的收藏不能删除。")
    if previous:
        checks.ensure_baseline(folder, state, cards)
        checks.preservation(folder, state, cards)
    if not pending:
        _totals(folder, state, sources, cards)
        return c.report(folder, state)
    _preview(runtime.run_json, folder, pending, session + "-preview")
    state["cleanup_preview"] = {"eligible_ids": pending, "retained_ids": [key for key in sources if key not in ids],
                                "authorization_sha256": state["sealed"][state["authorization"]],
                                "executed": False, "batch_size": batch_size, "max_batches": max_batches}
    save(folder, state)
    if not execute:
        return c.report(folder, state)
    _sources_and_outputs(runtime.run_json, folder, state, spec, sources, ids, cards)
    if not previous:
        intent = {"ids": ids, "lookup_urls": list(dict.fromkeys(
            url for key in ids for url in (sources[key]["url"], cards[key]["url"]))),
            "authorization_sha256": state["sealed"][state["authorization"]],
            "review_sha256": state["ready"]["review_sha256"]}
        seal(folder, state, "cleanup-intent.json", intent)
        state["cleanup"] = {**intent, "status": "intent"}
    checks.ensure_baseline(folder, state, cards)
    checks.preservation(folder, state, cards)
    request = {"created_at": _now(), "resume": resume, "batch_size": batch_size,
               "max_batches": max_batches, "remaining_ids": pending,
               "original_intent_sha256": state["sealed"]["cleanup-intent.json"]}
    seal(folder, state, session + "/request.json", request)
    state["cleanup"].setdefault("attempts", []).append(session + "/request.json")
    save(folder, state)
    for number, offset in enumerate(range(0, len(pending), batch_size), 1):
        if max_batches is not None and number > max_batches:
            break
        cards, verified = _batch(runtime.run_json, folder, state, spec, sources,
                                 pending[offset:offset + batch_size], cards, session, number)
        if not verified:
            break
    return c.report(folder, state)
