"""[INPUT]: Agent 审阅 JSON、来源 handoff 和目标规则所在目录。
[OUTPUT]: 校验/冻结的 approved、Soota 完成回执与产物指纹。
[POS]: 只验证机械契约；全文阅读、语义覆盖与大纲质量由 Agent 负责。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .workflow_sources import check_sources
from .workflow_state import (
    call,
    check_file,
    data,
    destination,
    digest,
    encoded,
    immutable,
    inside,
    path_key,
    read_json,
    require,
    save,
    seal,
    unseal,
)


def template(job: Path, state: dict) -> dict:
    bindings = unseal(job, state, "handoffs.json")
    sources = []
    for source in unseal(job, state, "sources.json"):
        handoff = bindings.get(source["id"])
        sources.append(
            {
                "id": source["id"],
                "source_sha256": source["source_sha256"],
                "coverage": "partial" if handoff else "missing",
                "all_valuable_parts_handled": False,
                "gaps": ["待 Agent 阅读完整来源、目标规则和相关既有笔记"],
                "review_notes": "",
                "submission": {
                    **{k: handoff[k] for k in ("task_id", "item_id", "context_fingerprint")},
                    "note_markdown": "",
                    "outline_markdown": "",
                }
                if handoff
                else None,
            }
        )
    return {"sources": sources, "notes": []}


def evidence_target(raw: str, base: Path, permitted: dict[str, set[str]]) -> str:
    require(isinstance(raw, str) and raw, "证据路径不能为空。")
    parsed = urlsplit(raw)
    require(not parsed.scheme and not parsed.netloc and not parsed.query, "证据必须链接本地 context。")
    path = str((base / unquote(parsed.path)).resolve())
    require(path in permitted and parsed.fragment in permitted[path], "引用了其他来源或不存在的证据。")
    return path


def links(markdown: str, base: Path, permitted: dict[str, set[str]]) -> set[str]:
    """证据必须绑定实际 context 路径；相同段落 ID 不能跨来源偷换。"""
    seen = set()
    for target in re.findall(r"\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)", markdown):
        raw = target[0] or target[1]
        parsed = urlsplit(raw)
        if not parsed.fragment.startswith(("para-", "seg-")) and not (
            Path(parsed.path).name in {"context.md", "transcript.md"} and parsed.fragment
        ):
            continue
        seen.add(evidence_target(raw, base, permitted))
    all_ids = set().union(*permitted.values()) if permitted else set()
    bare = set(re.findall(r"\[((?:para|seg)-[A-Za-z0-9_-]+)\]", markdown))
    require(bare <= all_ids, "引用了未知证据 ID。")
    return seen


def validate_outline(notes: list):
    count = 0

    def visit(node, depth):
        nonlocal count
        count += 1
        require(isinstance(node, dict) and not set(node) - {"text", "note", "children"}, "大纲节点字段无效。")
        require(isinstance(node.get("text"), str) and node["text"].strip(), "大纲 text 不能为空。")
        require("note" not in node or isinstance(node["note"], str), "大纲 note 必须是字符串。")
        children = node.get("children", [])
        require(isinstance(children, list) and depth <= 32 and count <= 500, "大纲超过 500 节点/32 层限制。")
        for child in children:
            visit(child, depth + 1)

    for note in notes:
        require(
            isinstance(note.get("outline"), dict) and note["outline"].get("text") == note["title"],
            "大纲根标题必须等于定稿笔记标题。",
        )
        visit(note["outline"], 1)
    require(len(encoded({"nodes": [n["outline"] for n in notes]})) <= 512 * 1024, "大纲超过 512 KiB。")


def validate(job: Path, state: dict, review: dict) -> dict:
    spec = unseal(job, state, "spec.json")
    sources = {s["id"]: s for s in unseal(job, state, "sources.json")}
    bindings = unseal(job, state, "handoffs.json")
    require(isinstance(review, dict) and set(review) == {"sources", "notes"}, "审阅仅接受 sources 和 notes。")
    entries, notes = review["sources"], review["notes"]
    require(isinstance(entries, list) and all(isinstance(x, dict) for x in entries), "sources 必须是对象数组。")
    require(
        len(entries) == len(sources) and {x.get("id") for x in entries} == set(sources),
        "sources 必须逐一覆盖本批 ID，不得重复或遗漏。",
    )
    reviews = {x["id"]: x for x in entries}
    submissions = {}
    for identity, item in reviews.items():
        require(
            set(item)
            == {"id", "source_sha256", "coverage", "all_valuable_parts_handled", "gaps", "review_notes", "submission"},
            "source 审阅字段不符。",
        )
        source, binding = sources[identity], bindings.get(identity)
        require(item["source_sha256"] == source["source_sha256"], "source_sha256 不匹配。")
        require(item["coverage"] in {"complete", "partial", "missing"}, "coverage 无效。")
        require(type(item["all_valuable_parts_handled"]) is bool, "all_valuable_parts_handled 必须是布尔值。")
        require(
            isinstance(item["gaps"], list) and all(isinstance(g, str) and g.strip() for g in item["gaps"]),
            "gaps 必须是非空说明的列表。",
        )
        require(
            isinstance(item["review_notes"], str) and item["review_notes"].strip(),
            "须由 Agent 记录实际审阅、完整性依据、目标规则及既有笔记核对结论。",
        )
        if not binding or source["protected"] or item["coverage"] == "missing":
            require(
                item["coverage"] == "missing"
                and not item["all_valuable_parts_handled"]
                and item["gaps"]
                and item["submission"] is None,
                "缺失/受保护来源不能伪装完整或提交产物。",
            )
            continue
        if item["coverage"] == "complete":
            require(not item["gaps"] and source["scope"] != "excerpt", "明确节选或仍有 gaps 的来源不能声明完整。")
        else:
            require(item["gaps"], "partial 来源须说明缺口。")
        submission = item["submission"]
        require(
            isinstance(submission, dict)
            and set(submission) == {"task_id", "item_id", "context_fingerprint", "note_markdown", "outline_markdown"},
            "submission 字段不符。",
        )
        require(
            all(submission[k] == binding[k] for k in ("task_id", "item_id", "context_fingerprint")),
            "submission task/item/context 身份不符。",
        )
        for field in ("note_markdown", "outline_markdown"):
            body = submission[field]
            require(isinstance(body, str) and body.strip(), f"缺少 {field}。")
            require(
                links(body, Path(binding["bundle"]), {binding["context"]: set(binding["evidence_ids"])}),
                "每个来源的 note/outline 必须引用自己的实际 context 证据。",
            )
        key = binding["item_id"]
        require(key not in submissions or submissions[key] == submission, "共享正文的同一 item 不能提交不同内容。")
        submissions[key] = submission
    require(isinstance(notes, list) and notes and all(isinstance(x, dict) for x in notes), "至少需要一份可发布笔记。")
    used, paths, titles = set(), set(), set()
    for note in notes:
        fields = {"title", "relative_path", "source_ids", "markdown", "body_sha256", "outline"}
        require(fields <= set(note) <= fields | {"evidence"}, "笔记字段不符，不能自行指定 destination/vault。")
        require(isinstance(note["title"], str) and note["title"].strip(), "笔记标题不能为空。")
        path = destination(spec, note["relative_path"])
        key = path_key(str(path))
        title = path_key(note["title"].strip())
        require(key not in paths and title not in titles, "笔记路径或主题标题重复。")
        paths.add(key)
        titles.add(title)
        ids = note["source_ids"]
        require(
            isinstance(ids, list)
            and ids
            and all(isinstance(x, str) for x in ids)
            and len(ids) == len(set(ids))
            and set(ids) <= set(sources),
            "笔记 source_ids 无效。",
        )
        require(
            all(
                not sources[x]["protected"] and reviews[x]["coverage"] != "missing" and reviews[x]["submission"]
                for x in ids
            ),
            "笔记引用受保护或缺失来源。",
        )
        require(isinstance(note["markdown"], str) and note["markdown"].strip(), "笔记正文不能为空。")
        require(digest(note["markdown"].encode()) == note["body_sha256"], "笔记 body_sha256 不符。")
        allowed = {bindings[x]["context"]: set(bindings[x]["evidence_ids"]) for x in ids}
        inline = links(note["markdown"], path.parent, allowed)
        if "evidence" in note:
            mapping = note["evidence"]
            require(isinstance(mapping, dict) and set(mapping) == set(ids), "独立 evidence 必须逐一覆盖 source_ids。")
            for identity in ids:
                targets = mapping[identity]
                require(isinstance(targets, list) and targets, "每个来源至少需要一个独立证据。")
                binding = bindings[identity]
                for target in targets:
                    evidence_target(target, path.parent, {binding["context"]: set(binding["evidence_ids"])})
        else:
            require(inline == set(allowed), "合并笔记必须分别引用每个 source_id 的实际 context。")
        if path.exists():
            check_file(path, note["body_sha256"])
        used.update(ids)
    for identity, item in reviews.items():
        require(
            not item["all_valuable_parts_handled"] or identity in used,
            "没有知识落点的来源不能声明所有有价值内容已处理。",
        )
    validate_outline(notes)
    return review


def artifact_checks(folder: Path, binding: dict) -> dict[str, str]:
    manifest = read_json(inside(folder, "manifest.json"))
    require(
        manifest.get("schema_version") == 2 and manifest.get("context_fingerprint") == binding["context_fingerprint"],
        "Soota 完成包身份或 context 指纹不符。",
    )
    result = {}
    for name in ("context.md", "note.md", "outline.md", "analysis.json"):
        matches = [a for a in manifest.get("artifacts", []) if a.get("path") == name]
        require(len(matches) == 1 and matches[0].get("verification") == "hash", f"缺少已验证产物：{name}")
        path = inside(folder, name)
        check_file(path, matches[0].get("sha256"))
        require(path.stat().st_size == matches[0].get("bytes") and path.stat().st_size > 0, "Soota 产物大小不符。")
        result[str(path)] = matches[0]["sha256"]
    saved = read_json(folder / "analysis.json")
    require(
        all(saved.get(k) == binding[k] for k in ("task_id", "item_id", "context_fingerprint")), "analysis 身份不符。"
    )
    result[str(folder / "manifest.json")] = digest((folder / "manifest.json").read_bytes())
    return result


def complete(run, job: Path, state: dict, review: dict):
    bindings = unseal(job, state, "handoffs.json")
    used = {identity for note in review["notes"] for identity in note["source_ids"]}
    submissions = {bindings[s["id"]]["item_id"]: s["submission"] for s in review["sources"] if s["submission"]}
    directory = job / "submissions"
    directory.mkdir(mode=0o700, exist_ok=True)
    for item, submission in submissions.items():
        immutable(directory / (digest(item.encode()) + ".json"), encoded(submission))
    require(len(list(directory.glob("*.json"))) == len(submissions), "提交目录含额外或过期提交。")
    result = data(
        call(
            run,
            job,
            "soota",
            ["jobs", "resume", state["soota_task_id"], "--analysis", str(directory), "--max-cost", "0", "--json"],
            "soota-resume",
            (0, 2),
        )
    )
    require(isinstance(result, dict) and result.get("job_id") == state["soota_task_id"], "恢复了不同 Soota 任务。")
    items = result.get("items", [])
    require(
        isinstance(items, list)
        and all(isinstance(x, dict) for x in items)
        and len({x.get("item_id") for x in items}) == len(items),
        "Soota 恢复条目无效或重复。",
    )
    by_id = {x.get("item_id"): x for x in items}
    checks = {}
    for identity in used:
        binding = bindings[identity]
        row = by_id.get(binding["item_id"], {})
        require(
            row.get("status") == "completed"
            and row.get("input_index") == binding["input_index"]
            and row.get("bundle") == binding["bundle"],
            f"来源 item 尚未完成：{identity}",
        )
        checks.update(artifact_checks(Path(binding["bundle"]), binding))
        saved = read_json(Path(binding["bundle"]) / "analysis.json")
        require(
            all(saved.get(k) == v for k, v in submissions[binding["item_id"]].items()), "实际 Soota 产物不是本次提交。"
        )
    seal(job, state, "completed-artifacts.json", checks)
    state["completed_source_ids"] = sorted(used)


def submit_review(run, job: Path, state: dict, review_file: Path):
    check_sources(job, state)
    review = validate(job, state, read_json(review_file))
    if "approved.json" in state.get("sealed", {}):
        require(encoded(review) == encoded(unseal(job, state, "approved.json")), "approved 已冻结；不能替换草稿。")
        check_approved(job, state)
        return
    seal(job, state, "candidate.json", review)
    state["status"] = "submitting"
    save(job, state)
    complete(run, job, state, review)
    check_sources(job, state)
    seal(job, state, "approved.json", review)
    seal(job, state, "outline.json", {"nodes": [n["outline"] for n in review["notes"]]})
    state["status"] = "approved"
    save(job, state)


def check_approved(job: Path, state: dict):
    check_sources(job, state)
    approved = unseal(job, state, "approved.json")
    for path, sha in unseal(job, state, "completed-artifacts.json").items():
        check_file(Path(path), sha)
    require(
        {s for n in approved["notes"] for s in n["source_ids"]} == set(state["completed_source_ids"]),
        "完成来源与 approved 不一致。",
    )
    unseal(job, state, "outline.json")
    return approved
