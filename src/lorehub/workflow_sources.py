"""[INPUT]: Cubox batch/folder list、可选 Soota v2 正文包。
[OUTPUT]: 不可变来源、输入顺序和实际 task/item/context 绑定。
[POS]: workflow 来源保全与接续；不把描述或本地 full 当作全文证明。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from .workflow_state import (
    call,
    check_file,
    data,
    digest,
    encoded,
    immutable,
    inside,
    read_json,
    require,
    rows,
    seal,
    unseal,
)


def batch(run, job: Path, ids: list[str], name: str) -> dict:
    ids_path = job / "requests" / (name + "-" + digest(encoded(ids)) + "-ids.txt")
    immutable(ids_path, ("\n".join(ids) + "\n").encode())
    result = data(
        call(
            run,
            job,
            "cubox",
            ["card", "batch", "--ids-file", str(ids_path), "--workers", "2", "-o", "json"],
            name,
            (0, 1),
        )
    )
    require(
        isinstance(result, dict) and result.get("kind") == "cubox_card_batch" and result.get("schema_version") == 1,
        "Cubox 未返回 batch 契约。",
    )
    items = result.get("items")
    require(isinstance(items, list) and all(isinstance(x, dict) for x in items), "Cubox batch items 无效。")
    require([x.get("id") for x in items] == ids, "Cubox 返回的 ID/顺序与请求不一致。")
    for item in items:
        require(item.get("status") in {"ok", "error", "skipped"}, "Cubox 条目状态无效。")
        if item["status"] == "ok":
            require(
                isinstance(item.get("card"), dict) and item["card"].get("id") == item["id"], "Cubox card 身份不符。"
            )
    return result


def folders(run, job: Path, name: str) -> list:
    result = rows(call(run, job, "cubox", ["folder", "list", "-o", "json"], name), "folder list")
    require(
        all(isinstance(x.get("id"), str) and isinstance(x.get("name"), str) for x in result),
        "文件夹缺少 ID/name；无法核实保护范围。",
    )
    require(len({x["id"] for x in result}) == len(result), "文件夹 ID 重复。")
    return result


def protected(card: dict, listing: list) -> bool:
    host = (urlsplit(card.get("url", "")).hostname or "").lower()
    domain = card.get("domain", "").lower()
    if any(x == "github.com" or x.endswith(".github.com") for x in (host, domain)):
        return True
    by_id = {x["id"]: x for x in listing}
    folder = card.get("folder")
    if not folder:
        return False
    # 只识别实际 name/nested_name 与 parent_id 链，不从卡片标题推断。
    seen = set()
    while folder:
        names = [folder.get("name", ""), *folder.get("nested_name", "").split("/")]
        if any("github" in name.casefold() for name in names):
            return True
        identity = folder.get("id")
        require(identity not in seen, "文件夹父链循环；无法核实保护范围。")
        seen.add(identity)
        known = by_id.get(identity)
        require(known is not None, "卡片文件夹不在 folder list；无法核实保护范围。")
        if any("github" in known.get(k, "").casefold() for k in ("name", "nested_name")):
            return True
        parent = known.get("parent_id")
        require(not parent or parent in by_id, "缺少父文件夹；无法核实保护范围。")
        folder = by_id.get(parent)
    return False


def url_identity(value: str):
    require(isinstance(value, str), "来源 URL 无效。")
    p = urlsplit(value)
    require(
        p.scheme in {"http", "https"} and p.hostname and not p.username and not p.password,
        "补抓来源必须是直接 HTTP(S) URL。",
    )
    host = p.hostname.lower()
    if host in {"twitter.com", "www.twitter.com", "mobile.twitter.com", "x.com", "www.x.com"}:
        match = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/status/([0-9]+)/?", p.path)
        require(match is not None, "补抓 Twitter 来源必须指向同一条原帖，不能是查询或账号。")
        return ("twitter", match[1].lower(), match[2])
    return (p.scheme, host, p.port, p.path or "/", p.query)


def supplement(job: Path, card: dict, supplied: str) -> tuple[bytes, dict]:
    original = Path(supplied).expanduser().resolve()
    if original.name == "manifest.json":
        original = original.parent
    manifest_path = inside(original, "manifest.json")
    manifest = read_json(manifest_path)
    require(manifest.get("schema_version") == 2, "补抓仅接受已校验的 Soota v2 正文包。")
    source, content = manifest.get("source", {}), manifest.get("content")
    if source.get("platform") == "native":
        return native_thread(job, card, original, manifest)
    require(isinstance(source, dict) and isinstance(content, dict), "补抓包缺少来源正文。")
    require(
        source.get("kind") not in {"operation", "native", "query", "search", "collection", "user", "file"}
        and source.get("platform") not in {"native", "local", "operation"},
        "查询/native 包不能冒充原帖。",
    )
    target = url_identity(card.get("url", ""))
    for field in ("url", "canonical_url"):
        require(url_identity(source.get(field)) == target, "补抓 bundle 来源与原收藏 URL 不匹配。")
    if target[0] == "twitter":
        require(
            source.get("platform") == "twitter" and source.get("kind") == "post" and source.get("id") == target[2],
            "Twitter 来源身份不符。",
        )
    content_source = content.get("source", {})
    require(
        all(content_source.get(k) == source.get(k) for k in ("platform", "kind", "id", "url", "canonical_url")),
        "正文与 manifest 来源身份不符。",
    )
    require(isinstance(content.get("blocks"), list) and content["blocks"], "补抓包没有实际正文块。")
    artifacts = manifest.get("artifacts", [])
    require(isinstance(artifacts, list) and all(isinstance(a, dict) for a in artifacts), "补抓产物契约无效。")
    files = {}
    for name, kind in (("body.md", "body"), ("context.md", "context")):
        entries = [a for a in artifacts if a.get("path") == name]
        require(
            len(entries) == 1 and entries[0].get("kind") == kind and entries[0].get("verification") == "hash",
            f"补抓包缺少已验证 {name}。",
        )
        path = inside(original, name)
        check_file(path, entries[0].get("sha256"))
        require(path.stat().st_size == entries[0].get("bytes"), "补抓产物长度不符。")
        files[str(path)] = entries[0]["sha256"]
    require(manifest.get("context_fingerprint") == files[str(original / "context.md")], "补抓 context 指纹不符。")
    body = (original / "body.md").read_bytes()
    require(body.strip(), "补抓正文为空。")
    if content.get("body_markdown") is not None:
        require(body == content["body_markdown"].encode("utf-8"), "补抓正文与 manifest 不符。")
    files[str(manifest_path)] = digest(manifest_path.read_bytes())
    snapshot = job / "supplements" / digest(encoded(source))
    immutable(snapshot / "manifest.json", manifest_path.read_bytes())
    immutable(snapshot / "context.md", (original / "context.md").read_bytes())
    return body, {
        "bundle": str(original),
        "source": source,
        "provider": manifest.get("processing", {}).get("provider"),
        "scope": content.get("scope", "unknown"),
        "files": files,
        "snapshot": str(snapshot),
    }


def native_thread(job: Path, card: dict, original: Path, manifest: dict) -> tuple[bytes, dict]:
    source = manifest["source"]
    operation = "opencli.twitter.thread"
    require(
        source.get("kind") == "query" and source.get("url") == operation and source.get("canonical_url") == operation,
        "仅支持已绑定的原生 twitter.thread 数据包。",
    )
    target = url_identity(card.get("url", ""))
    require(target[0] == "twitter", "原生 thread 包只能补充对应 X 帖子。")
    artifacts = [a for a in manifest.get("artifacts", []) if a.get("path") == "data.json"]
    require(
        len(artifacts) == 1
        and artifacts[0].get("kind") == "data"
        and artifacts[0].get("format") == "json"
        and artifacts[0].get("provider") == "opencli"
        and artifacts[0].get("verification") == "hash",
        "原生包缺少已验证 OpenCLI data.json。",
    )
    path = inside(original, "data.json")
    check_file(path, artifacts[0].get("sha256"))
    raw = path.read_bytes()
    require(len(raw) == artifacts[0].get("bytes"), "原生 data.json 长度不符。")
    values = read_json(path)
    require(isinstance(values, list) and all(isinstance(x, dict) for x in values), "thread 数据必须是对象数组。")
    matched = [x for x in values if x.get("id") == target[2]]
    require(
        len(matched) == 1
        and url_identity(matched[0].get("url")) == target
        and isinstance(matched[0].get("text"), str)
        and matched[0]["text"].strip(),
        "原生 thread 数据未包含唯一的目标帖 ID、URL 和正文。",
    )
    # 当前 v2 manifest 不保存 query params。若后续提供 params，也必须和结果同帖。
    native = manifest.get("native")
    if native is not None:
        require(isinstance(native, dict) and isinstance(native.get("params"), dict), "native params 契约不明。")
        value = native["params"].get("tweet-id")
        require(
            value == target[2] or isinstance(value, str) and url_identity(value) == target,
            "原生请求 tweet-id 与收藏不符。",
        )
    manifest_path = original / "manifest.json"
    files = {str(path): digest(raw), str(manifest_path): digest(manifest_path.read_bytes())}
    snapshot = job / "supplements" / digest(encoded(source))
    immutable(snapshot / "manifest.json", manifest_path.read_bytes())
    immutable(snapshot / "data.json", raw)
    return raw, {
        "bundle": str(original),
        "source": source,
        "provider": "opencli",
        "scope": "unknown",
        "format": "native_thread_json",
        "target_id": target[2],
        "files": files,
        "snapshot": str(snapshot),
    }


def collect(run, job: Path, state: dict, ids: list[str], supplied: dict):
    listing = folders(run, job, "prepare-folders")
    result = batch(run, job, ids, "prepare-cards")
    seal(job, state, "cubox-snapshot.json", result)
    seal(job, state, "folders.json", listing)
    sources, inputs = [], []
    by_path = {}
    for row in result["items"]:
        card = row.get("card") or {}
        item = {
            "id": row["id"],
            "status": row["status"],
            "content_status": row.get("content_status"),
            "protected": protected(card, listing) if row["status"] == "ok" else True,
            "url": card.get("url"),
            "title": card.get("title"),
            "error": row.get("error"),
            "source_sha256": None,
            "source_path": None,
            "scope": "unknown",
            "origin": None,
        }
        # 即使被保护也保存真实 source.text；永远不拼入 description/insight。
        body = card.get("content") if row.get("content_status") == "body_available" else None
        if isinstance(body, str) and body.strip():
            raw = body.encode("utf-8")
            item["origin"] = "cubox"
        else:
            raw = None
        if row["id"] in supplied:
            require(row["status"] == "ok" and not item["protected"], "受保护或读取失败来源不能接入补抓包。")
            if raw is not None:
                item["cubox_body_path"] = str(job / "sources" / digest(raw) / "source.txt")
                immutable(Path(item["cubox_body_path"]), raw)
            raw, item["supplement"] = supplement(job, card, supplied[row["id"]])
            item.update(origin="soota_bundle", scope=item["supplement"]["scope"])
        if raw is not None:
            path = job / "sources" / digest(raw) / "source.txt"
            item.update(source_sha256=immutable(path, raw), source_path=str(path))
            if not item["protected"]:
                if str(path) not in by_path:
                    by_path[str(path)] = len(inputs)
                    inputs.append({"path": str(path), "source_ids": []})
                inputs[by_path[str(path)]]["source_ids"].append(row["id"])
        sources.append(item)
    seal(job, state, "sources.json", sources)
    seal(job, state, "source-inputs.json", {"inputs": [row["path"] for row in inputs]})
    seal(job, state, "input-map.json", inputs)


def handoffs(run, job: Path, state: dict):
    inputs = unseal(job, state, "input-map.json")
    bindings = {}
    if inputs:
        output = job / "bundles"
        output.mkdir(mode=0o700)
        result = data(
            call(
                run,
                job,
                "soota",
                [
                    "ingest",
                    "--inputs-file",
                    str(job / "source-inputs.json"),
                    "--provider",
                    "local",
                    "--want",
                    "context,note,outline",
                    "--workers",
                    "2",
                    "--max-cost",
                    "0",
                    "--max-items",
                    str(len(inputs)),
                    "--output",
                    str(output),
                    "--json",
                ],
                "soota-ingest",
                (0, 2),
            )
        )
        require(
            isinstance(result, dict)
            and isinstance(result.get("job_id"), str)
            and isinstance(result.get("items"), list),
            "Soota 没有返回任务条目。",
        )
        state["soota_task_id"] = result["job_id"]
        seen = set()
        for row in result["items"]:
            index = row.get("input_index")
            require(
                type(index) is int and 0 <= index < len(inputs) and index not in seen, "Soota input_index 无效或重复。"
            )
            seen.add(index)
            if row.get("status") not in {"waiting_analysis", "completed"}:
                continue
            require(isinstance(row.get("bundle"), str), "Soota 接续条目缺少 bundle。")
            folder = Path(row["bundle"]).resolve()
            require(folder.is_relative_to(output), "Soota bundle 超出本批输出目录。")
            request_path, context_path = inside(folder, "analysis-request.json"), inside(folder, "context.md")
            request = read_json(request_path)
            require(
                request.get("task_id") == result["job_id"] and request.get("item_id") == row.get("item_id"),
                "Soota handoff task/item 身份不符。",
            )
            check_file(context_path, request.get("context_fingerprint"))
            require(Path(request.get("context", "")).resolve() == context_path, "handoff context 路径不符。")
            require(
                {"note", "outline"} <= set(request.get("requested_outputs", [])), "handoff 缺少 note/outline 目标。"
            )
            evidence = re.findall(r'<a id="((?:para|seg)-[A-Za-z0-9_-]+)"></a>', context_path.read_text())
            require(evidence and len(set(evidence)) == len(evidence), "context 缺少稳定证据 ID 或 ID 重复。")
            binding = {
                "task_id": result["job_id"],
                "item_id": row["item_id"],
                "input_index": index,
                "bundle": str(folder),
                "context": str(context_path),
                "context_fingerprint": request["context_fingerprint"],
                "request_sha256": digest(request_path.read_bytes()),
                "evidence_ids": evidence,
            }
            for identity in inputs[index]["source_ids"]:
                bindings[identity] = binding
    seal(job, state, "handoffs.json", bindings)


def check_sources(job: Path, state: dict):
    for source in unseal(job, state, "sources.json"):
        if source["source_path"]:
            path = Path(source["source_path"])
            require(path.resolve().is_relative_to(job), "source 路径越界。")
            check_file(path, source["source_sha256"])
        for path, sha in source.get("supplement", {}).get("files", {}).items():
            check_file(Path(path), sha)
    for handoff in unseal(job, state, "handoffs.json").values():
        folder = Path(handoff["bundle"])
        check_file(inside(folder, "context.md"), handoff["context_fingerprint"])
        check_file(inside(folder, "analysis-request.json"), handoff["request_sha256"])


def reread(run, job: Path, state: dict, ids: list[str], name: str):
    if not ids:
        return
    initial = {x["id"]: x for x in unseal(job, state, "cubox-snapshot.json")["items"]}
    for row in batch(run, job, ids, name)["items"]:
        old = initial[row["id"]]
        # 原本不可读的保留项也必须保持同一失败状态，不能声称正文保全已核验。
        if old["status"] != "ok":
            require(row == old, f"保留来源状态已变化：{row['id']}")
        else:
            require(
                row["status"] == "ok" and row["card"] == old["card"] and row["content_status"] == old["content_status"],
                f"来源快照已变化：{row['id']}",
            )
