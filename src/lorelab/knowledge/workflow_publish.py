"""[INPUT]: 冻结 approved、大纲、目标文件及 Mubu 全树回执。
[OUTPUT]: 独立文章交付、按需单次导入意图和基于节点 ID 的全树对账。
[POS]: 唯一写入者；遇未知结果只能读取，不重发导入。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from .workflow_review import check_approved
from .workflow_state import (
    WorkflowError,
    call,
    check_file,
    data,
    destination,
    digest,
    lock,
    mubu_args,
    path_key,
    read_json,
    require,
    save,
    seal,
    sync_dir,
    unseal,
    wants_outline,
)


@contextmanager
def writer(spec: dict):
    # 保留旧锁命名空间，新旧入口及已在运行的 LoreHub 共同串行化同一目的地。
    root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "lorehub/locks"
    key = (
        ("mubu-" + digest(spec["mubu_doc"].encode()))
        if wants_outline(spec)
        else ("article-" + digest(spec["destination"].encode()))
    )
    with lock(root / (key + ".lock")):
        yield


def document(run, job: Path, spec: dict, name: str) -> dict:
    result = call(run, job, "mubu", mubu_args(spec, "nodes", spec["mubu_doc"], "--include-html"), name)
    require(isinstance(result, dict) and result.get("ok") is True, "幕布全树读取未成功。")
    tree = data(result)
    require(
        isinstance(tree, dict)
        and tree.get("doc_id") == spec["mubu_doc"]
        and type(tree.get("version")) is int
        and tree["version"] >= 0
        and isinstance(tree.get("nodes"), list),
        "幕布全树契约无效。",
    )
    seen, children = {}, {}
    for node in tree["nodes"]:
        require(
            isinstance(node, dict)
            and isinstance(node.get("node_id"), str)
            and node["node_id"]
            and node["node_id"] not in seen,
            "幕布节点 ID 无效或重复。",
        )
        require(
            isinstance(node.get("text"), str)
            and isinstance(node.get("note"), str)
            and "text_html" in node
            and "note_html" in node
            and "images" in node
            and isinstance(node.get("path"), list),
            "幕布节点缺少完整字段。",
        )
        parent = node.get("parent_id")
        require(parent is None or parent in seen, "幕布节点父级缺失或顺序不完整。")
        children.setdefault(parent, []).append(node["node_id"])
        expected_path = (seen[parent]["path"] + ["children"] if parent else ["nodes"]) + [len(children[parent]) - 1]
        require(node["path"] == expected_path, "幕布树路径或兄弟顺序不一致。")
        seen[node["node_id"]] = node
    require(
        all(n.get("child_count") == len(children.get(n["node_id"], [])) for n in tree["nodes"]), "幕布全树缺少后代。"
    )
    return tree


def inspect_notes(job: Path, state: dict, approved: dict, *, require_saved: bool):
    spec = unseal(job, state, "spec.json")
    for note in approved["notes"]:
        path = destination(spec, note["relative_path"])
        if require_saved:
            require(state.get("notes", {}).get(note["relative_path"]) == note["body_sha256"], "笔记写入尚未登记。")
            check_file(path, note["body_sha256"])
        elif path.exists() or path.is_symlink():
            try:
                check_file(path, note["body_sha256"])
            except WorkflowError as exc:
                raise WorkflowError(f"已有笔记不同或被修改：{path}；请由 Agent 独立审阅合并，首版不会覆盖。") from exc


def write_notes(job: Path, state: dict, approved: dict):
    inspect_notes(job, state, approved, require_saved=False)
    spec = unseal(job, state, "spec.json")
    for note in approved["notes"]:
        path = destination(spec, note["relative_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # 再次检查父路径；O_EXCL 保证另一写入者的新文件不被覆盖。
        path = destination(spec, note["relative_path"])
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            check_file(path, note["body_sha256"])
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(note["markdown"].encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            sync_dir(path.parent)
        check_file(path, note["body_sha256"])
        state.setdefault("notes", {})[note["relative_path"]] = note["body_sha256"]
        save(job, state)


def check_tree(before: dict, after: dict, roots: list[str], outlines: list[dict], parent: str | None):
    require(
        after["version"] == before["version"] + 1 and after.get("name") == before.get("name"),
        "幕布版本或文档名不符合单次追加预期。",
    )
    prior = {n["node_id"]: n for n in before["nodes"]}
    current = {n["node_id"]: n for n in after["nodes"]}
    require(
        len(roots) == len(outlines) and len(set(roots)) == len(roots) and not set(roots) & prior.keys(),
        "执行返回的 root_ids 无效；不能使用预览 ID。",
    )
    for identity, old in prior.items():
        expected = dict(old)
        if identity == parent:
            expected["child_count"] += len(roots)
        require(current.get(identity) == expected, f"幕布原节点未保全：{identity}")
    children = {}
    for node in after["nodes"]:
        children.setdefault(node["parent_id"], []).append(node["node_id"])
    prior_siblings = [n["node_id"] for n in before["nodes"] if n["parent_id"] == parent]
    require(children.get(parent, []) == prior_siblings + roots, "新主题位置或旧兄弟顺序不符。")
    added = set()

    def visit(identity, expected, expected_parent):
        actual = current.get(identity)
        require(actual is not None and identity not in prior and identity not in added, "新节点缺失或身份混淆。")
        added.add(identity)
        require(
            actual["parent_id"] == expected_parent
            and actual["text"] == expected["text"]
            and actual["note"] == expected.get("note", "")
            and actual["images"] == [],
            "新大纲内容与定稿不符。",
        )
        actual_children, expected_children = children.get(identity, []), expected.get("children", [])
        require(len(actual_children) == len(expected_children), "新大纲后代不完整。")
        for child, desired in zip(actual_children, expected_children, strict=True):
            visit(child, desired, identity)

    for identity, outline in zip(roots, outlines, strict=True):
        visit(identity, outline, parent)
    require(set(current) == set(prior) | added, "整篇幕布出现非本次预期的节点。")


def execution_evidence(job: Path, state: dict, spec: dict):
    intent = state["mubu"]
    result_file = job / "receipts" / "mubu-execute.json"
    if "mubu-result.json" not in state.get("sealed", {}) and result_file.is_file():
        seal(job, state, "mubu-result.json", read_json(result_file))
        save(job, state)
    if "mubu-result.json" in state.get("sealed", {}):
        result = data(unseal(job, state, "mubu-result.json"))
        if isinstance(result, dict) and result.get("doc_id") == spec["mubu_doc"] and result.get("action") == "import":
            if isinstance(result.get("root_ids"), list) and result.get("executed") is True:
                intent["root_ids"] = result["root_ids"]
            if isinstance(result.get("operation_id"), str):
                intent["operation_id"] = result["operation_id"]
            save(job, state)


def reconcile(run, job: Path, state: dict, approved: dict, *, checker=check_approved) -> bool:
    spec = unseal(job, state, "spec.json")
    inspect_notes(job, state, approved, require_saved=True)
    if not wants_outline(spec):
        checker(job, state)
        state["article"] = {"status": "verified"}
        state["status"] = "verified"
        save(job, state)
        return True
    intent = state.get("mubu")
    if not intent:
        return False
    execution_evidence(job, state, spec)
    before = unseal(job, state, "mubu-before.json")
    after = document(run, job, spec, "mubu-readback")
    roots = intent.get("root_ids")
    if not roots and intent.get("operation_id"):
        result = call(
            run,
            job,
            "mubu",
            mubu_args(spec, "operation-status", intent["operation_id"], "--verify"),
            "mubu-operation",
            (0, 1, 2, 3),
        )
        proof = data(result)
        if (
            isinstance(proof, dict)
            and proof.get("operation_id") == intent["operation_id"]
            and proof.get("doc_id") == spec["mubu_doc"]
            and proof.get("status") == "verified"
            and proof.get("verification_scope") == "whole_document"
        ):
            old_ids = {n["node_id"] for n in before["nodes"]}
            roots = [
                n["node_id"]
                for n in after["nodes"]
                if n["parent_id"] == spec["mubu_parent"] and n["node_id"] not in old_ids
            ]
    if not roots:
        intent.update(status="uncertain", reason="缺少执行 root_ids 或已记录操作的完整核验；禁止重导入。")
        state["status"] = "publish_uncertain"
        save(job, state)
        return False
    try:
        check_tree(before, after, roots, [n["outline"] for n in approved["notes"]], spec["mubu_parent"])
    except WorkflowError:
        intent["status"] = "uncertain"
        state["status"] = "publish_uncertain"
        save(job, state)
        raise
    checker(job, state)
    inspect_notes(job, state, approved, require_saved=True)
    intent.update(status="verified", root_ids=roots, verified_version=after["version"])
    state["status"] = "verified"
    save(job, state)
    return True


def publish_approved(run, job: Path, state: dict, *, checker=check_approved, write_articles: bool = True):
    approved = checker(job, state)
    spec = unseal(job, state, "spec.json")
    with writer(spec):
        if not wants_outline(spec):
            require(write_articles, "文章交付须启用正文写入。")
            write_notes(job, state, approved)
            reconcile(run, job, state, approved, checker=checker)
            return
        if state.get("mubu"):
            # 包括超时、conflict 和调用前崩溃；永不再次进入写路径。
            reconcile(run, job, state, approved, checker=checker)
            return
        before = document(run, job, spec, "mubu-before-read")
        parent = spec["mubu_parent"]
        require(parent is None or parent in {n["node_id"] for n in before["nodes"]}, "幕布父节点不存在。")
        titles = {path_key(n["text"].strip()) for n in before["nodes"] if n["parent_id"] == parent}
        require(
            not titles & {path_key(n["title"].strip()) for n in approved["notes"]},
            "已有同名主题根；请独立审阅合并，不能重复追加。",
        )
        args = [
            "node-import",
            spec["mubu_doc"],
            *(["--node-id", parent] if parent else ["--root"]),
            "--file",
            str(job / "outline.json"),
        ]
        result = call(run, job, "mubu", mubu_args(spec, *args), "mubu-preview")
        preview = data(result)
        require(
            isinstance(preview, dict)
            and preview.get("status") == "preview"
            and preview.get("executed") is False
            and preview.get("version") == before["version"],
            "幕布预览与当前版本不符；未执行。",
        )
        inspect_notes(job, state, approved, require_saved=False)
        if write_articles:
            write_notes(job, state, approved)
        else:
            inspect_notes(job, state, approved, require_saved=True)
        checker(job, state)
        seal(job, state, "mubu-before.json", before)
        state["mubu"] = {
            "status": "intent",
            "expected_version": before["version"],
            "outline_sha256": state["sealed"]["outline.json"],
            "root_ids": [],
            "operation_id": None,
        }
        state["status"] = "publishing"
        save(job, state)  # 调用之前落盘并 fsync；即使进程被杀也禁止再次导入。
        try:
            result = call(
                run,
                job,
                "mubu",
                mubu_args(spec, *args, "--expect-version", str(preview["version"]), "--execute"),
                "mubu-execute",
                (0, 1, 2, 3),
            )
            seal(job, state, "mubu-result.json", result)
            save(job, state)
        except Exception:
            state["mubu"]["status"] = "uncertain"
            state["status"] = "publish_uncertain"
            save(job, state)
            raise
        reconcile(run, job, state, approved, checker=checker)
