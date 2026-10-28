"""[INPUT]: 真实文章清单、用户反馈、新材料与 Agent 分类审阅。
[OUTPUT]: 可预览、可恢复、可撤回的分类及导航更新；原文保持原位。
[POS]: library 的反馈闭环；语义判断由当前 Agent 完成，不调用额外模型。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from . import library
from . import library_allocation as allocation
from . import library_taxonomy as adaptive
from .workflow_publish import writer
from .workflow_state import (
    atomic,
    default_root,
    destination,
    encoded,
    inside,
    open_job,
    read_json,
    require,
    save,
    seal,
    unseal,
    write_json,
)

INDEX = "图书馆目录.md"
CONTROLS = (library.TAXONOMY_FILE, INDEX)


def controls(root: Path) -> dict:
    return {name: (inside(root, name).read_bytes().decode("utf-8") if inside(root, name).exists() else None)
            for name in CONTROLS}


def fingerprints(catalog: dict) -> dict:
    return {item["relative_path"]: item["body_sha256"] for item in catalog["articles"]}


def prepare(vault: Path, subdir: str, feedback: str = "", context: Path | None = None,
            state_root: Path | None = None) -> dict:
    vault = vault.expanduser().resolve()
    spec = {"kind": "library-evolution", "vault": str(vault), "subdir": subdir,
            "destination": str(vault / subdir), "with_outline": False}
    target = destination(spec)
    require(target.is_dir(), "请先初始化知识目录。")
    root = Path(state_root or default_root().parent / "library-evolution").expanduser().resolve()
    require(not root.is_relative_to(vault) and not vault.is_relative_to(root), "演进记录必须与知识库分离。")
    with writer(spec):
        taxonomy = library.load(target)
        require(taxonomy is not None, "请先运行 knowledge library init。")
        observed = library.catalog(target, taxonomy)
        before = controls(target)
        allocation_start = allocation.start(target, taxonomy)
        new_context = context.read_text(encoding="utf-8") if context else None
    job = root / uuid4().hex
    job.mkdir(parents=True, mode=0o700)
    state = {"schema_version": 1, "job": str(job), "status": "waiting_review", "sealed": {}}
    seal(job, state, "spec.json", spec)
    seal(job, state, "before.json", before)
    seal(job, state, "observed.json", {**observed, "feedback": feedback, "context": new_context,
                                     "allocation_start": allocation_start})
    entries = taxonomy["categories"] if taxonomy["schema_version"] == 2 else []
    template = {"rationale": "", "categories": [
        {"key": e["code"], "name": e["name"], "parent": e.get("parent"), "scope": e["scope"],
         "evidence": [a["relative_path"] for a in observed["articles"] if a["category"] == e["code"]]}
        for e in entries], "assignments": [], "unassigned": []}
    write_json(job / "review-template.json", template)
    save(job, state)
    return {"ok": True, "job": str(job), "review_template": str(job / "review-template.json"),
            "observed": str(job / "observed.json"), "article_count": observed["count"],
            "instruction": "实读相关正文和反馈；少量短名，一层优先。不变的归属自动保留。新类别 key 用 new:短名，"
                           "evidence 指向文章路径、@feedback 或 @context。分类与排序由数组顺序表达；不搬原文。"}


def _review(before: dict, observed: dict, review: dict) -> dict:
    require(isinstance(review, dict) and set(review) == {"rationale", "categories", "assignments", "unassigned"},
            "分类审阅字段不符。")
    require(isinstance(review["rationale"], str) and review["rationale"].strip(), "须说明本次调整解决什么实际问题。")
    entries = review["categories"]
    require(isinstance(entries, list) and all(isinstance(e, dict) for e in entries), "categories 必须为对象数组。")
    old = {e["code"]: e for e in before["categories"]} if before["schema_version"] == 2 else {}
    known = {a["relative_path"] for a in observed["articles"]}
    evidence = known | ({"@feedback"} if observed["feedback"].strip() else set())
    evidence |= {"@context"} if observed["context"] else set()
    keys, next_code = {}, observed["allocation_start"]
    for entry in entries:
        require(set(entry) == {"key", "name", "parent", "scope", "evidence"}, "类别审阅字段不符。")
        key = entry["key"]
        require(isinstance(key, str) and key not in keys, "类别 key 缺失或重复。")
        if key in old:
            keys[key] = key
        else:
            require(re.fullmatch(r"new:[a-zA-Z][a-zA-Z0-9_-]{0,63}", key), "新类别 key 须使用 new:短名。")
            keys[key] = f"K{next_code:04}"
            next_code += 1
        refs = entry["evidence"]
        require(isinstance(refs, list) and refs and all(isinstance(p, str) and p in evidence for p in refs),
                "每个类别须有本次观察中的文章、反馈或新材料依据。")
        adaptive.safe_name(entry["name"])
        require(entry["parent"] is None or isinstance(entry["parent"], str), "parent 无效。")
    result = []
    pending = {e["key"]: e for e in entries}
    by_key = {}
    while pending:
        progressed = False
        for key, entry in list(pending.items()):
            parent = entry["parent"]
            require(parent is None or parent in keys, "父类别缺失。")
            if parent is not None and parent not in by_key:
                continue
            path = old[key]["path"] if key in old else (
                (by_key[parent]["path"] + "/" if parent else "") + entry["name"])
            item = {"code": keys[key], "name": entry["name"], "parent": keys.get(parent),
                    "order": list(keys).index(key), "path": path, "scope": entry["scope"]}
            by_key[key] = item
            result.append(item)
            del pending[key]
            progressed = True
        require(progressed, "类别父级存在循环。")
    assigned = {a["relative_path"]: a["category"] for a in observed["articles"]
                if a["category"] is not None or a["relative_path"] in before.get("assignments", {})}
    touched = set()
    for field in ["assignments", "unassigned"]:
        require(isinstance(review[field], list), f"{field} 必须为数组。")
        for item in review[field]:
            expected = {"path", "reason", *(["category"] if field == "assignments" else [])}
            require(isinstance(item, dict) and set(item) == expected, "文章归类字段不符。")
            path = item["path"]
            require(isinstance(path, str) and path in known and path not in touched, "文章路径未知或重复分配。")
            require(isinstance(item["reason"], str) and item["reason"].strip(), "须说明归类或暂不归类依据。")
            touched.add(path)
            if field == "assignments":
                require(isinstance(item["category"], str) and item["category"] in keys, "归属类别未知。")
                assigned[path] = keys[item["category"]]
            else:
                assigned[path] = None
    active = set(keys.values())
    require(set(assigned.values()) - {None} <= active, "退役类别仍有文章，须明确重新归类或保留为未归类。")
    retired = set(before.get("retired_codes", [])) | ({e["code"] for e in before["categories"]} - active)
    taxonomy = {"schema_version": 2, "id": before["id"], "version": before["version"] + 1,
                "title": before["title"], "categories": result, "assignments": assigned,
                "retired_codes": sorted(retired), "next_code": next_code,
                "exclude_files": sorted(set(before.get("exclude_files", [])) | {INDEX, "知识索引.md"})}
    return adaptive.validate(taxonomy)


def index_markdown(taxonomy: dict, observed: dict) -> str:
    records = observed["articles"]
    lines = ["# " + taxonomy["title"], "", "按实际内容归类，短名、一层优先。编号只用于导航排序，类别身份和原文路径保持稳定。",
             "", f"分类版本：{taxonomy['version']}。共 {len(records)} 篇文章。", "",
             "类别来自共享 `分类体系.json`；调整由 LoreLab 保留观察、依据、版本与回退记录。", ""]
    grouped = {}
    for item in records:
        grouped.setdefault(taxonomy["assignments"].get(item["relative_path"]), []).append(item)
    for label, entry in adaptive.ordered(taxonomy):
        rows = grouped.get(entry["code"], [])
        lines.extend([f"## {label} {entry['name']}", "", entry["scope"], ""])
        for item in rows:
            text = item["title"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            lines.append(f"- [{text}]({quote(item['relative_path'])})")
        if not rows:
            lines.append("暂未直接归入文章。")
        lines.append("")
    if grouped.get(None):
        lines.extend(["## 待归类", ""])
        for item in grouped[None]:
            text = item["title"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            lines.append(f"- [{text}]({quote(item['relative_path'])})")
    lines.extend(["", "原文不因归类而移动或复制；新文章按当前类别目录归档。分类调整不删除来源、不启动额外模型。", ""])
    return "\n".join(lines)


def plan(job: Path, state: dict, review: dict) -> dict:
    before_files = unseal(job, state, "before.json")
    before = library.validate(json.loads(before_files[library.TAXONOMY_FILE].encode("utf-8")))
    observed = unseal(job, state, "observed.json")
    taxonomy = _review(before, observed, review)
    unchanged = dict(taxonomy, version=before["version"])
    if unchanged == before:
        taxonomy = before
    old_assign = {a["relative_path"]: a["category"] for a in observed["articles"]}
    assigned = taxonomy["assignments"]
    summary = {"articles": observed["count"], "classified_before": sum(c is not None for c in old_assign.values()),
               "classified_after": sum(c is not None for c in assigned.values()), "categories_before": len(before["categories"]),
               "categories_after": len(taxonomy["categories"]),
               "reclassified": sum(old_assign[p] != assigned.get(p) for p in old_assign), "files_moved": 0,
               "quality_note": "覆盖数与变更量只证明结构结果；是否更好找须以实际检索和用户反馈检验。"}
    after = {library.TAXONOMY_FILE: encoded(taxonomy).decode(), INDEX: index_markdown(taxonomy, observed)}
    return {"review": review, "taxonomy": taxonomy, "after": after, "summary": summary,
            "allocation": [observed["allocation_start"], taxonomy["next_code"]]}


def preview(value: str, file: Path) -> dict:
    with open_job(value) as (job, state):
        result = plan(job, state, read_json(file))
        return {"ok": True, "job": str(job), **result["summary"], "tree": library.tree(result["taxonomy"])}


def _current(job: Path, state: dict) -> tuple[Path, dict]:
    spec = unseal(job, state, "spec.json")
    require(spec.get("kind") == "library-evolution", "不是分类演进任务。")
    root = destination(spec)
    observed = unseal(job, state, "observed.json")
    require(fingerprints(library.catalog(root)) == fingerprints(observed),
            "文章集合或正文已改变，请重新观察；不覆盖当前内容。")
    return root, controls(root)


def _write(root: Path, name: str, body: str | None):
    path = inside(root, name)
    if body is None:
        path.unlink(missing_ok=True)
    else:
        atomic(path, body.encode("utf-8"))


def apply(value: str, file: Path | None = None) -> dict:
    with open_job(value) as (job, state), writer(unseal(job, state, "spec.json")):
        require(state["status"] != "rolled_back", "任务已撤回，请重新准备。")
        if "plan.json" in state["sealed"]:
            result = unseal(job, state, "plan.json")
            require(file is None or read_json(file) == result["review"], "执行方案已冻结，不能替换。")
        else:
            require(file is not None, "首次 apply 需要 --file 审阅文件。")
            result = plan(job, state, read_json(file))
        root, current = _current(job, state)
        before, after = unseal(job, state, "before.json"), result["after"]
        require(all(current[n] in (before[n], after[n]) for n in CONTROLS), "分类或导航有新的人工修改，已保留。")
        if "plan.json" not in state["sealed"]:
            seal(job, state, "plan.json", result)
        state["status"] = "applying"
        save(job, state)
        allocation.reserve(root, library.validate(json.loads(before[library.TAXONOMY_FILE].encode("utf-8"))),
                           job, result["allocation"])
        for name in CONTROLS:
            require(controls(root)[name] in (before[name], after[name]), "执行期间文件已改变。")
            if controls(root)[name] != after[name]:
                _write(root, name, after[name])
        require(controls(root) == after, "分类更新未完整回读，保留任务供恢复。")
        require(fingerprints(library.catalog(root)) == fingerprints(unseal(job, state, "observed.json")), "原文已改变。")
        state["status"] = "applied"
        save(job, state)
        return {"ok": True, "job": str(job), "status": state["status"], **result["summary"]}


def rollback(value: str) -> dict:
    with open_job(value) as (job, state), writer(unseal(job, state, "spec.json")):
        result = unseal(job, state, "plan.json")
        root, current = _current(job, state)
        before, after = unseal(job, state, "before.json"), result["after"]
        require(all(current[n] in (before[n], after[n]) for n in CONTROLS), "后续修改已发生，不覆盖它们。")
        state["status"] = "rolling_back"
        save(job, state)
        for name in CONTROLS:
            require(controls(root)[name] in (before[name], after[name]), "撤回期间文件已改变。")
            if controls(root)[name] != before[name]:
                _write(root, name, before[name])
        require(controls(root) == before, "撤回未完整回读，保留任务供恢复。")
        state["status"] = "rolled_back"
        save(job, state)
        return {"ok": True, "job": str(job), "status": state["status"], "files_moved": 0}


def status(value: str) -> dict:
    with open_job(value) as (job, state):
        root = destination(unseal(job, state, "spec.json"))
        expected = unseal(job, state, "before.json")
        if state["status"] == "applied":
            expected = unseal(job, state, "plan.json")["after"]
        return {"ok": True, "job": str(job), "status": state["status"], "controls_match": controls(root) == expected,
                "articles_unchanged": fingerprints(library.catalog(root)) ==
                fingerprints(unseal(job, state, "observed.json"))}
