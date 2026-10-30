"""[INPUT]: 外部 X 材料清单、Agent 开放式审阅、真实文章和 Cubox 仓库卡片。
[OUTPUT]: 固定来源集合、增量审阅与缺口清单、整体交付核对和版本化策略反馈。
[POS]: knowledge 的轻量集合账本；不生成文章、不调用模型或更改分类。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from . import runtime
from .workflow_publish import writer
from .workflow_sources import batch
from .workflow_state import (
    WorkflowError,
    check_file,
    default_root,
    destination,
    digest,
    encoded,
    open_job,
    read_json,
    require,
    save,
    seal,
    unseal,
    write_json,
)

PRODUCT = Path(__file__).resolve().parents[3]


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label} 必须是非空文字。")
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]+", value), "Cubox/X ID 必须是数字字符串。")
    return value


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute(), "必须提供绝对路径。")
    path = Path(value)
    require(path.resolve() == path and not path.is_symlink(), f"路径包含链接或歧义：{path}")
    return path


def separate(left, right):
    require(not left.is_relative_to(right) and not right.is_relative_to(left), "材料、状态、产品与知识目录必须分离。")


def files(value, root, checked=None):
    require(isinstance(value, list) and value, "必须保存原始文件证据及指纹。")
    result = []
    for entry in value:
        require(isinstance(entry, dict) and set(entry) == {"path", "sha256"}, "文件证据必须是 path/sha256。")
        path = absolute(entry["path"])
        require(path.is_relative_to(root), "原始材料或证据超出 materials_root。")
        if checked is not None and str(path) in checked:
            require(checked[str(path)] == entry["sha256"], "共享原始文件登记了冲突指纹。")
        else:
            check_file(path, entry["sha256"])
            if checked is not None:
                checked[str(path)] = entry["sha256"]
        result.append(dict(entry))
    require(len({e["path"] for e in result}) == len(result), "文件证据重复。")
    return result


def x_status(url, status_id):
    require(isinstance(url, str), "URL 与 X status ID 不符。")
    parsed = urlsplit(url)
    require(parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() in {"twitter.com", "www.twitter.com", "mobile.twitter.com",
                                         "x.com", "www.x.com", "mobile.x.com"},
            "URL 与 X status ID 不符。")
    match = re.fullmatch(r"/(?:[A-Za-z0-9_]{1,15}|i/web)/status/([0-9]+)/?", parsed.path)
    require(match is not None and match.group(1) == status_id, "URL 与 X status ID 不符。")


def repository(url):
    text(url, "仓库 URL")
    parsed = urlsplit(url)
    require(parsed.scheme == "https" and parsed.netloc.lower() == "github.com"
            and not parsed.query and not parsed.fragment, "必须是直接 HTTPS GitHub 仓库 URL。")
    match = re.fullmatch(r"/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/?", parsed.path)
    require(match is not None, "必须指向 owner/repository，不能是 GitHub 提及或搜索链接。")
    owner, name = match.groups()
    require(owner.lower() not in {"settings", "orgs", "users", "topics", "collections", "marketplace", "features"}
            and name not in {".", ".."}, "不是仓库 URL。")
    return (owner.casefold(), name.removesuffix(".git").casefold())


def prepare(file: Path, state_root: Path | None = None):
    file = absolute(str(file.expanduser().absolute()))
    manifest = read_json(file)
    require(isinstance(manifest, dict) and manifest.get("schema_version") == 1, "collection manifest 版本无效。")
    target = absolute(manifest.get("destination"))
    require(target.is_dir(), "destination 必须已存在。")
    materials = absolute(manifest.get("materials_root", str(file.parent)))
    require(materials.is_dir() and file.is_relative_to(materials), "清单必须在 materials_root 中。")
    root = Path(state_root or default_root().parent / "collections").expanduser().absolute()
    root = absolute(str(root))
    for private in (materials, root):
        separate(private, target)
        separate(private, PRODUCT)
    separate(target, PRODUCT)
    entries = manifest.get("sources")
    require(isinstance(entries, list) and entries, "sources 必须包含完整选定集合。")
    sources, ids, checked = [], set(), {}
    for entry in entries:
        require(isinstance(entry, dict), "来源必须是对象。")
        card_id, status_id = identifier(entry.get("id")), identifier(entry.get("status_id"))
        require(card_id not in ids, "重复 Cubox ID。多个收藏可共用同一 X status 的证据。")
        ids.add(card_id)
        x_status(entry.get("url"), status_id)
        raw = files(entry.get("raw_files"), materials, checked)
        availability = entry.get("availability")
        require(availability in {"collected", "missing"}, "availability 只能是 collected/missing。")
        source_path, sha = None, None
        if availability == "collected":
            source_path = absolute(entry.get("text_file"))
            require(source_path.is_relative_to(materials), "正文超出 materials_root。")
            body = source_path.read_bytes()
            require(body.decode("utf-8").strip(), "已抓文本不能为空。")
            sha = digest(body)
            raw = [e for e in raw if e["path"] != str(source_path)] + [{"path": str(source_path), "sha256": sha}]
        else:
            require(entry.get("text_file") is None, "missing 不能携带正文或宣称完整。")
        sources.append({"id": card_id, "status_id": status_id, "url": entry["url"],
                        "availability": availability, "text_file": str(source_path) if source_path else None,
                        "text_sha256": sha, "raw_files": raw})
    spec = {"kind": "cubox-x-collection", "destination": str(target), "vault": str(target), "subdir": "",
            "with_outline": False, "materials_root": str(materials),
            "manifest": {"path": str(file), "sha256": digest(file.read_bytes())}}
    job = root / uuid4().hex
    job.mkdir(parents=True, mode=0o700)
    state = {"schema_version": 1, "job": str(job), "status": "waiting_review", "sealed": {},
             "reviews": {}, "feedback": []}
    seal(job, state, "spec.json", spec)
    seal(job, state, "sources.json", sources)
    write_json(job / "review-template.json", {"schema_version": 1, "sources": [
        {"id": s["id"], "source_sha256": s["text_sha256"], "read_sha256": None,
         "decision": "retain", "strategy": "", "rationale": "", "coverage": "", "complete": False,
         "gaps": ["尚未实读审阅"], "outputs": []} for s in sources]})
    save(job, state)
    return report(job, state)


@contextmanager
def opened(value):
    with open_job(value) as (job, state):
        spec = unseal(job, state, "spec.json")
        require(spec.get("kind") == "cubox-x-collection", "不是 collection 任务。")
        destination(spec)
        check_file(Path(spec["manifest"]["path"]), spec["manifest"]["sha256"])
        checked = {}
        for source in unseal(job, state, "sources.json"):
            files(source["raw_files"], Path(spec["materials_root"]), checked)
        yield job, state, spec


def reviews(job, state):
    return {key: unseal(job, state, name) for key, name in state["reviews"].items()}


def mutable(state):
    require(not state.get("cleanup"), "删除意图已冻结；只能只读对账，不能改审阅或授权。")


def validate_review(source, review, spec):
    require(isinstance(review, dict), "review 必须是对象。")
    for field in ("strategy", "rationale", "coverage"):
        text(review.get(field), field)
    require(review.get("source_sha256") == source["text_sha256"], "review 来源指纹不符。")
    require(review.get("read_sha256") in (None, source["text_sha256"]), "实读指纹不符。")
    require(type(review.get("complete")) is bool, "complete 必须为布尔值。")
    require(isinstance(review.get("gaps"), list) and all(isinstance(x, str) and x.strip() for x in review["gaps"]),
            "gaps 必须是文字数组。")
    require(isinstance(review.get("outputs"), list), "outputs 必须是数组。")
    decision = review.get("decision")
    require(decision in {"processed", "retain", "confirmed-unavailable", "reviewed-no-yield"}, "decision 无效。")
    if decision == "confirmed-unavailable":
        require(review["complete"] is False and review["gaps"] and not review["outputs"],
                "失效不能伪装正文完整或已总结，必须保留 gaps，不能登记交付。")
        evidence = review.get("unavailable_evidence")
        require(isinstance(evidence, dict), "失效必须有单独的证据。")
        x_status(evidence.get("url"), source["status_id"])
        require(evidence.get("code") in {"NotFound", "HTTP404", "HTTP410"},
                "失效证据仅接受 NotFound/HTTP404/HTTP410；AuthorizationError 或超时不能冒充失效。")
        text(evidence.get("reason"), "失效原因")
        try:
            observed = datetime.fromisoformat(text(evidence.get("observed_at"), "失效观察时间"))
            require(observed.tzinfo is not None, "失效观察时间须带时区。")
        except ValueError as exc:
            raise WorkflowError("失效观察时间无效。") from exc
        files(evidence.get("files"), Path(spec["materials_root"]))
    elif decision == "reviewed-no-yield":
        require(source["text_sha256"] and review.get("read_sha256") == source["text_sha256"]
                and review["complete"] is True and review["gaps"] == [] and review["outputs"] == [],
                "reviewed-no-yield 必须完整实读、无 gaps 且 outputs=[]；缺失来源或未读媒体不能冒充无新知识。")
        text(review.get("no_yield_reason"), "no_yield_reason")
    elif decision == "processed":
        require(source["text_sha256"] and review.get("read_sha256") == source["text_sha256"]
                and review["complete"] is True and review["gaps"] == [] and review["outputs"],
                "processed 必须完整实读、无 gaps 且有实际输出，缺失来源不能伪装完整。")
    else:
        require(review["complete"] is False, "retain 不能标成正文已完整处理。")
    return review


def verify_outputs(run, job, state, spec, selected, *, cards=None):
    repositories, seen_articles = {}, {}
    source_ids = {s["id"] for s in unseal(job, state, "sources.json")}
    for source_id, review in selected.items():
        seen = set()
        for output in review["outputs"]:
            require(isinstance(output, dict), "输出引用必须为对象。")
            kind = output.get("kind")
            if kind == "article":
                require(set(output) == {"kind", "path", "sha256"}, "文章引用必须含 path/sha256。")
                path = destination(spec, output["path"])
                check_file(path, output["sha256"])
                require(path.read_text(encoding="utf-8").strip(), "文章正文为空。")
                require(str(path) not in seen_articles or seen_articles[str(path)] == output["sha256"],
                        "同一文章登记了不同指纹。")
                seen_articles[str(path)] = output["sha256"]
                key = (kind, str(path))
            elif kind == "repository":
                require(set(output) == {"kind", "url", "cubox_id"}, "仓库引用必须含 url/cubox_id。")
                identity = repository(output["url"])
                card_id = identifier(output["cubox_id"])
                require(card_id not in source_ids,
                        "仓库输出不能使用本批 X 来源 ID。")
                require(card_id not in repositories or repositories[card_id] == identity, "仓库卡片身份冲突。")
                repositories[card_id] = identity
                key = (kind, identity)
            else:
                raise WorkflowError("输出仅支持真实 article/repository 引用。")
            require(key not in seen, f"{source_id} 重复输出引用。")
            seen.add(key)
    if cards is not None or len(repositories) > 100:
        from .collection_cleanup import inventory

        if cards is None:
            cards = inventory(run, job, "collection-repositories")
        for card_id, identity in repositories.items():
            require(card_id in cards, "GitHub 输出卡片未真实回读。")
            require(repository(cards[card_id].get("url")) == identity, "GitHub 输出卡片 URL 不符。")
    for offset in range(0, len(repositories) if cards is None else 0, 100):
        result = batch(run, job, list(repositories)[offset:offset + 100], f"collection-repositories-{offset}")
        for item in result["items"]:
            require(item["status"] == "ok", "GitHub 输出卡片未真实回读。")
            require(repository(item["card"].get("url")) == repositories[item["id"]], "GitHub 输出卡片 URL 不符。")
    return {"articles": seen_articles, "repositories": {k: list(v) for k, v in repositories.items()}}


def submit(job: str, file: Path):
    submitted = read_json(file)
    require(isinstance(submitted, dict) and submitted.get("schema_version") == 1
            and isinstance(submitted.get("sources"), list) and submitted["sources"], "review 契约无效。")
    with opened(job) as (folder, state, spec):
        mutable(state)
        sources = {s["id"]: s for s in unseal(folder, state, "sources.json")}
        selected = {}
        for review in submitted["sources"]:
            require(isinstance(review, dict) and review.get("id") in sources, "review 来源越界。")
            key = review["id"]
            require(key not in selected, "review 来源重复。")
            selected[key] = validate_review(sources[key], review, spec)
        combined = {**reviews(folder, state), **selected}
        with writer(spec):
            proof = verify_outputs(runtime.run_json, folder, state, spec, combined)
        for key, review in selected.items():
            name = f"reviews/{key}-{digest(encoded(review))}.json"
            seal(folder, state, name, review)
            state["reviews"][key] = name
        state.update(status="reviewed", verification=proof)
        state.pop("ready", None)
        save(folder, state)
        return report(folder, state)


def inspect(run, job, state, spec, *, cards=None):
    selected, blockers = reviews(job, state), []
    for source in unseal(job, state, "sources.json"):
        key, review = source["id"], selected.get(source["id"])
        if review is None:
            blockers.append({"id": key, "reason": "尚未实读审阅"})
            continue
        validate_review(source, review, spec)
        if review["decision"] == "retain" and not (source["text_sha256"]
                                                    and review.get("read_sha256") == source["text_sha256"]):
            blockers.append({"id": key, "reason": "未读或缺失来源仍保留，阻塞全批 ready"})
    proof = verify_outputs(run, job, state, spec, selected, cards=cards)
    result = {"ready": not blockers, "blockers": blockers, "verification": proof,
              "checked_at": datetime.now(UTC).isoformat(),
              "review_sha256": {key: state["sealed"][name] for key, name in state["reviews"].items()}}
    state["ready"] = result
    save(job, state)
    return result


def report(job, state, selected=None):
    sources = unseal(job, state, "sources.json")
    selected = reviews(job, state) if selected is None else selected
    counts = dict.fromkeys(("processed", "retain", "confirmed-unavailable", "reviewed-no-yield"), 0)
    for review in selected.values():
        counts[review["decision"]] += 1
    pending = [s["id"] for s in sources if s["id"] not in selected]
    retained = [{"id": source["id"], "status_id": source["status_id"],
                 "text_file": source["text_file"], "gaps": selected[source["id"]]["gaps"]}
                for source in sources
                if selected.get(source["id"], {}).get("decision") == "retain"]
    return {"ok": state["status"] not in {"cleanup_uncertain", "cleanup_blocked"}, "job": str(job),
            "status": state["status"], "sources": sources, "reviewed_ids": list(state["reviews"]),
            "source_count": len(sources), "status_count": len({s["status_id"] for s in sources}),
            "reviewed_source_count": len(selected), "review_counts": counts,
            "pending_source_count": len(pending), "retained_sources": retained,
            "review_files": {key: str(job / name) for key, name in state["reviews"].items()},
            "pending_source_ids": pending,
            "review_template": str(job / "review-template.json"), "ready": state.get("ready"),
            "strategy_version": len(state["feedback"]), "feedback": list(state["feedback"]),
            "strategy": unseal(job, state, state["feedback"][-1])["strategy"] if state["feedback"] else None,
            "authorization": state.get("authorization"), "cleanup": state.get("cleanup"),
            "cleanup_error": state.get("cleanup_error"),
            "cleanup_preview": state.get("cleanup_preview"),
            "scope": "本地状态不代表云端当前状态；ready/cleanup 实时核对，完整性与语义仍须 Agent 实读。"}


def status(job):
    with opened(job) as (folder, state, spec):
        sources = {s["id"]: s for s in unseal(folder, state, "sources.json")}
        selected = reviews(folder, state)
        for key, review in selected.items():
            validate_review(sources[key], review, spec)
        return report(folder, state, selected)


def ready(job):
    with opened(job) as (folder, state, spec), writer(spec):
        from .collection_cleanup import live_sources

        sources = {s["id"]: s for s in unseal(folder, state, "sources.json")}
        deleted = set(state.get("cleanup", {}).get("absent_ids", []))
        live_sources(runtime.run_json, folder, sources, [key for key in sources if key not in deleted],
                     "collection-verify-sources")
        result = inspect(runtime.run_json, folder, state, spec)
        return {**report(folder, state), "ok": result["ready"]}


verify = ready
review = submit


def feedback(job, file):
    value = read_json(file)
    require(isinstance(value, dict) and value.get("schema_version") == 1, "反馈版本无效。")
    for field in ("strategy", "rationale"):
        text(value.get(field), field)
    with opened(job) as (folder, state, spec), writer(spec):
        mutable(state)
        version = len(state["feedback"])
        require(type(value.get("base_version")) is int and value["base_version"] == version, "策略版本已改变。")
        keys = value.get("source_ids")
        require(isinstance(keys, list) and keys and all(isinstance(k, str) for k in keys)
                and len(set(keys)) == len(keys), "反馈必须引用明确的来源证据。")
        selected = reviews(folder, state)
        require(set(keys) <= set(selected) and all(selected[k]["decision"] == "processed" for k in keys),
                "反馈须基于已有真实交付的已处理来源。")
        proof = verify_outputs(runtime.run_json, folder, state, spec, {k: selected[k] for k in keys})
        rollback = value.get("rollback_to")
        if rollback is not None:
            require(type(rollback) is int and 1 <= rollback <= version, "策略回退版本无效。")
            previous = unseal(folder, state, state["feedback"][rollback - 1])
            require(previous["strategy"] == value["strategy"], "回退策略与历史版本不符。")
        record = {**value, "version": version + 1, "previous_version": version,
                  "evidence": {k: {"review": state["reviews"][k],
                                   "sha256": state["sealed"][state["reviews"][k]]} for k in keys},
                  "verification": proof}
        name = f"feedback/{version + 1}-{digest(encoded(record))}.json"
        seal(folder, state, name, record)
        state["feedback"].append(name)
        save(folder, state)
        return report(folder, state)


def authorize(job, file):
    from .collection_cleanup import authorize as authorize_cleanup

    return authorize_cleanup(job, file)


def cleanup(job, execute=False, *, batch_size=100, max_batches=None, resume=False):
    from .collection_cleanup import cleanup as clean

    return clean(job, execute, batch_size=batch_size, max_batches=max_batches, resume=resume)
