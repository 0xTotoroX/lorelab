"""仅供 workflow 回归测试的 CLI 契约替身，所有来源均为合成数据。"""

import hashlib
import html
import json
from copy import deepcopy
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def card(identity, *, content=None, url=None, folder=None, status="body_available"):
    return {
        "id": identity,
        "status": "ok",
        "content_status": status,
        "error": None,
        "card": {
            "id": identity,
            "title": "Synthetic " + identity,
            "url": url or "https://example.org/" + identity,
            "content": content if content is not None else "  Source " + identity + "\r\n\r\nEvidence.\n",
            "description": "Description must not become original body",
            "folder": folder,
            "domain": "example.org",
            "tags": [],
            "annotations": [],
            "update_time": "fixed",
        },
    }


def artifact(folder, name, kind):
    raw = (folder / name).read_bytes()
    return {
        "path": name,
        "kind": kind,
        "sha256": sha(raw),
        "bytes": len(raw),
        "verification": "hash",
        "format": "json" if name.endswith("json") else "md",
        "provider": "local",
    }


class FakeCLI:
    def __init__(self, cards):
        self.cards = {x["id"]: deepcopy(x) for x in cards}
        self.folder_rows = []
        self.calls = []
        self.items = []
        self.nodes = [{"id": "old-root", "text": "Existing", "note": "Preserved", "children": []}]
        self.version = 7
        self.imports = self.deletes = 0
        self.mode = "verified"
        self.delete_timeout = False
        self.incomplete = set()
        self.reverse_items = True
        self.archived = set()
        self.counter = 0

    def __call__(self, tool, args, receipt=None, acceptable_codes=(0,)):
        self.calls.append((tool, list(args), acceptable_codes))
        value = self._run(tool, args, receipt)
        if receipt:
            write(receipt, value)
        return value

    def _run(self, tool, args, receipt):
        def arg(flag):
            return args[args.index(flag) + 1]

        if tool == "cubox":
            if args[:2] == ["folder", "list"]:
                return deepcopy(self.folder_rows)
            if args[:2] == ["card", "batch"]:
                ids = Path(arg("--ids-file")).read_text().splitlines()
                items = [
                    deepcopy(
                        self.cards.get(
                            x,
                            {
                                "id": x,
                                "status": "error",
                                "card": None,
                                "content_status": None,
                                "error": {"code": "missing"},
                            },
                        )
                    )
                    for x in ids
                ]
                return {"schema_version": 1, "kind": "cubox_card_batch", "items": items, "counts": {"total": len(ids)}}
            if args[:2] == ["card", "list"]:
                assert "--all" in args
                return [
                    deepcopy(x["card"])
                    for identity, x in self.cards.items()
                    if x["status"] == "ok"
                    and x["card"]["url"] == arg("--url")
                    and (identity in self.archived) == ("--archived" in args)
                ] or None
            if args[0] == "delete":
                assert "--keep-empty-tags" in args
                ids = arg("--id").split(",")
                if "--dry-run" in args:
                    return {"dry_run": True, "count": len(ids), "cards": [{"id": x} for x in ids]}
                self.deletes += 1
                for identity in ids:
                    self.cards.pop(identity, None)
                if self.delete_timeout:
                    raise RuntimeError("simulated delete timeout")
                return {"dry_run": False, "count": len(ids)}
        if tool == "soota":
            if args[0] == "ingest":
                want = arg("--want").split(",")
                assert want in [["context", "note"], ["context", "note", "outline"]]
                assert arg("--provider") == "local" and arg("--workers") == "2" and arg("--max-cost") == "0"
                inputs = json.loads(Path(arg("--inputs-file")).read_text())["inputs"]
                for i, path in enumerate(inputs):
                    folder = Path(arg("--output")) / f"bundle-{i}"
                    folder.mkdir()
                    context = f'<a id="para-{i}"></a>\n[para-{i}] ' + Path(path).read_bytes().decode()
                    (folder / "context.md").write_bytes(context.encode())
                    request = {
                        "task_id": "task-1",
                        "item_id": f"item-{i}",
                        "context_fingerprint": sha(context),
                        "context": str(folder / "context.md"),
                        "requested_outputs": want[1:],
                    }
                    write(folder / "analysis-request.json", request)
                    write(
                        folder / "manifest.json",
                        {
                            "schema_version": 2,
                            "context_fingerprint": sha(context),
                            "artifacts": [artifact(folder, "context.md", "context")],
                        },
                    )
                    self.items.append(
                        {"item_id": f"item-{i}", "input_index": i, "status": "waiting_analysis", "bundle": str(folder)}
                    )
                return self.result()
            if args[:2] == ["jobs", "resume"]:
                assert arg("--max-cost") == "0" and acceptable_resume(args)
                for path in Path(arg("--analysis")).glob("*.json"):
                    submission = json.loads(path.read_text())
                    row = next(x for x in self.items if x["item_id"] == submission["item_id"])
                    folder = Path(row["bundle"])
                    for name, field in (("note.md", "note_markdown"), ("outline.md", "outline_markdown")):
                        if field in submission:
                            (folder / name).write_text(submission[field] + "\n\n[原文](context.md)\n")
                    write(folder / "analysis.json", submission)
                    manifest = json.loads((folder / "manifest.json").read_text())
                    manifest["artifacts"] = [
                        artifact(folder, name, kind)
                        for name, kind in (
                            ("context.md", "context"),
                            ("note.md", "note"),
                            ("outline.md", "outline"),
                            ("analysis.json", "analysis"),
                        )
                        if (folder / name).is_file()
                    ]
                    write(folder / "manifest.json", manifest)
                    row["status"] = "waiting_analysis" if row["item_id"] in self.incomplete else "completed"
                return self.result()
        if tool == "mubu":
            assert args[:2] == ["--agent", "--auth"] and args[2] in {"desktop", "password"}
            command, identity = args[3:5]
            if command == "nodes":
                assert "--include-html" in args and "--depth" not in args
                return self.envelope(
                    {"doc_id": identity, "name": "Synthetic document", "version": self.version, "nodes": self.flat()}
                )
            if command == "operation-status":
                assert "--verify" in args
                return self.envelope(
                    {
                        "doc_id": "doc",
                        "operation_id": identity,
                        "status": "verified",
                        "verification_scope": "whole_document",
                    }
                )
            if command == "node-import":
                if "--execute" not in args:
                    return self.envelope(
                        {
                            "status": "preview",
                            "version": self.version,
                            "executed": False,
                            "root_ids": ["preview-never-use"],
                        }
                    )
                self.imports += 1
                assert int(arg("--expect-version")) == self.version
                outlines = json.loads(Path(arg("--file")).read_text())["nodes"]

                def node(value):
                    self.counter += 1
                    return {
                        "id": f"new-{self.counter}",
                        "text": value["text"],
                        "note": value.get("note", ""),
                        "children": [node(x) for x in value.get("children", [])],
                    }

                additions = [node(n) for n in outlines]
                dest = self.nodes
                if "--node-id" in args:
                    dest = next(x for x in self.nodes if x["id"] == arg("--node-id"))["children"]
                dest.extend(additions)
                self.version += 1
                result = self.envelope(
                    {
                        "doc_id": identity,
                        "action": "import",
                        "executed": True,
                        "status": "uncertain" if self.mode == "uncertain" else "verified",
                        "operation_id": "a" * 32,
                        "root_ids": [n["id"] for n in additions],
                    }
                )
                if self.mode == "operation_only":
                    result["data"].pop("root_ids")
                if self.mode in {"timeout", "receipt_timeout"}:
                    if self.mode == "receipt_timeout":
                        write(receipt, result)
                    raise RuntimeError("simulated import timeout")
                return result
        raise AssertionError((tool, args))

    def result(self):
        return {
            "ok": False,
            "code": "waiting_analysis",
            "data": {
                "job_id": "task-1",
                "job_status": "waiting_analysis",
                "items": deepcopy(self.items[::-1] if self.reverse_items else self.items),
            },
        }

    def envelope(self, data):
        return {"ok": True, "status": data.get("status", "ok"), "schema_version": 1, "data": data}

    def flat(self):
        result = []

        def visit(nodes, parent, path, ancestors):
            for index, node in enumerate(nodes):
                current_path = [*path, index]
                result.append(
                    {
                        "node_id": node["id"],
                        "text": node["text"],
                        "note": node["note"],
                        "text_html": "<span>" + html.escape(node["text"]) + "</span>",
                        "note_html": "<span>" + html.escape(node["note"]) + "</span>",
                        "parent_id": parent,
                        "path": current_path,
                        "ancestors": ancestors,
                        "images": [],
                        "child_count": len(node["children"]),
                    }
                )
                visit(
                    node["children"],
                    node["id"],
                    [*current_path, "children"],
                    [*ancestors, {"node_id": node["id"], "text": node["text"]}],
                )

        visit(self.nodes, None, ["nodes"], [])
        return result


def acceptable_resume(args):
    return args[2] == "task-1" and "--force" not in args


def review_for(result, vault, *, selected=None, complete=True):
    selected = selected if selected is not None else list(result["handoffs"])
    review = json.loads(Path(result["review_template"]).read_text())
    notes = []
    for source in review["sources"]:
        source["review_notes"] = "Read source, target rules and existing notes; synthetic review evidence."
        if source["id"] not in selected:
            source.update(
                coverage="missing",
                all_valuable_parts_handled=False,
                gaps=["Retained for supplementation"],
                submission=None,
            )
            continue
        binding = result["handoffs"][source["id"]]
        evidence = binding["evidence_ids"][0]
        source.update(
            coverage="complete" if complete else "partial",
            all_valuable_parts_handled=True,
            gaps=[] if complete else ["Original coverage unverified"],
        )
        source["submission"].update(
            note_markdown=f"# Point\n\nEvidence [source](context.md#{evidence})",
            **(
                {"outline_markdown": f"- Point [source](context.md#{evidence})"}
                if "outline_markdown" in source["submission"]
                else {}
            ),
        )
        title = "Topic " + source["id"]
        text = f"# {title}\n\nPoint [source](<{binding['context']}#{evidence}>)\n"
        notes.append(
            {
                "title": title,
                "relative_path": title + ".md",
                "source_ids": [source["id"]],
                "markdown": text,
                "body_sha256": sha(text),
                **(
                    {"outline": {"text": title, "children": [{"text": "Point", "children": [{"text": "Condition"}]}]}}
                    if "outline_markdown" in source["submission"]
                    else {}
                ),
            }
        )
    review["notes"] = notes
    return review
