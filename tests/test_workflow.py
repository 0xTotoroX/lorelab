"""跨工具主链、安全门禁及崩溃恢复；仅 mock CLI，不访问账号。"""

import json
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from test_workflow_support import FakeCLI, artifact, card, review_for, sha, write

from lorehub import workflow as w
from lorehub.workflow_state import WorkflowError, lock


@pytest.fixture
def setup(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "global-state"))

    def start(cards=None, **kwargs):
        fake = FakeCLI(cards or [card("a")])
        monkeypatch.setattr(w, "run_json", fake)
        ids = tmp_path / "ids.txt"
        ids.write_text("\n".join(fake.cards))
        result = w.prepare(ids, vault, "Knowledge", "doc", state_root=tmp_path / "jobs", **kwargs)
        return fake, result, vault

    return start


def approve(result, vault, **options):
    review = review_for(result, vault, **options)
    path = Path(result["job"]) / "review.json"
    write(path, review)
    return w.submit(result["job"], path), path, review


def test_full_chain_dryrun_and_recovery_once(setup):
    fake, result, vault = setup([card("a"), card("missing", status="description_only")], delete_verified=True)
    source = result["sources"][0]
    assert Path(source["source_path"]).read_bytes() == fake.cards["a"]["card"]["content"].encode()
    assert result["sources"][1]["source_path"] is None
    assert result["pending_source_ids"] == ["missing"]
    approved, path, _review = approve(result, vault)
    assert approved["status"] == "approved"
    write(path, {"changed": "mutable Agent draft is no longer read"})
    published = w.publish(result["job"])
    assert published["status"] == "verified" and fake.imports == 1
    assert w.verify(result["job"])["status"] == "verified"
    preview = w.cleanup(result["job"])
    assert preview["cleanup_preview"]["eligible_ids"] == ["a"] and fake.deletes == 0
    cleaned = w.cleanup(result["job"], execute=True)
    assert cleaned["status"] == "cleaned" and cleaned["retained_ids"] == ["missing"]
    assert fake.deletes == 1 and "missing" in fake.cards
    assert w.cleanup(result["job"], execute=True)["status"] == "cleaned"
    assert w.publish(result["job"])["status"] == "cleaned"
    assert w.verify(result["job"])["status"] == "cleaned"
    assert fake.imports == fake.deletes == 1
    assert list((vault / "Knowledge").glob("*.md"))
    for name in ("job.json", "approved.json", "sources.json"):
        assert (Path(result["job"]) / name).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "relative",
    [
        "../escape.md",
        "/tmp/escape.md",
        "a/../../escape.md",
        "a\\escape.md",
        ".obsidian/config.md",
        "AGENTS.md",
        "a//b.md",
        "a/./b.md",
        "x.txt",
    ],
)
def test_path_escape_rejected(setup, relative):
    fake, result, vault = setup()
    review = review_for(result, vault)
    review["notes"][0]["relative_path"] = relative
    path = Path(result["job"]) / "review.json"
    write(path, review)
    with pytest.raises(WorkflowError):
        w.submit(result["job"], path)
    assert fake.imports == fake.deletes == 0


def test_symlink_destination_and_changed_parent(setup, tmp_path):
    fake, result, vault = setup()
    approve(result, vault)
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "Knowledge").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkflowError, match="符号链接"):
        w.publish(result["job"])
    assert not list(outside.iterdir()) and fake.imports == 0


def test_input_index_not_return_position(setup):
    _fake, result, vault = setup([card("a"), card("b")])
    assert result["handoffs"]["a"]["item_id"] == "item-0"
    assert result["handoffs"]["b"]["item_id"] == "item-1"
    approve(result, vault)
    assert w.publish(result["job"])["status"] == "verified"


def test_partial_batch_and_soota_waiting_other_items(setup):
    failed = {"id": "error", "status": "error", "content_status": None, "card": None, "error": {"code": "timeout"}}
    fake, result, vault = setup([card("a"), card("b"), failed], delete_verified=True)
    approve(result, vault, selected=["a"])
    assert fake.items[1]["status"] == "waiting_analysis"
    w.publish(result["job"])
    cleaned = w.cleanup(result["job"], execute=True)
    assert cleaned["cleanup"]["ids"] == ["a"]
    assert cleaned["retained_ids"] == ["b", "error"]
    assert cleaned["cleanup"]["retained_unreadable_ids"] == ["error"]


@pytest.mark.parametrize("kind", ["description_only", "link_only", "empty"])
def test_missing_cannot_claim_complete(setup, kind):
    _fake, result, vault = setup([card("a"), card("b", status=kind)])
    review = review_for(result, vault)
    review["sources"][1].update(coverage="complete", all_valuable_parts_handled=True, gaps=[])
    path = Path(result["job"]) / "review.json"
    write(path, review)
    with pytest.raises(WorkflowError, match="伪装完整"):
        w.submit(result["job"], path)


def test_github_direct_and_descendant_protected(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    fake = FakeCLI(
        [
            card("safe"),
            card("direct", url="https://github.com/example/repository"),
            card("child", folder={"id": "child", "name": "Tools"}),
        ]
    )
    fake.folder_rows = [
        {"id": "parent", "name": "GitHub 项目", "parent_id": None},
        {"id": "child", "name": "Tools", "parent_id": "parent"},
    ]
    monkeypatch.setattr(w, "run_json", fake)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "global"))
    ids = tmp_path / "ids"
    ids.write_text("safe\ndirect\nchild")
    result = w.prepare(ids, vault, "Knowledge", "doc", delete_verified=True, state_root=tmp_path / "jobs")
    assert [x["protected"] for x in result["sources"]] == [False, True, True]
    approve(result, vault)
    w.publish(result["job"])
    assert w.cleanup(result["job"], True)["cleanup"]["ids"] == ["safe"]
    assert set(fake.cards) == {"direct", "child"}


def test_unauthorized_and_partial_never_delete(setup):
    fake, result, vault = setup()
    approve(result, vault)
    w.publish(result["job"])
    assert w.cleanup(result["job"], True)["cleanup_preview"]["eligible_ids"] == []
    assert fake.deletes == 0


def test_partial_published_but_retained(setup):
    fake, result, vault = setup(delete_verified=True)
    approve(result, vault, complete=False)
    w.publish(result["job"])
    assert w.cleanup(result["job"], True)["cleanup_preview"]["eligible_ids"] == []
    assert fake.deletes == 0


@pytest.mark.parametrize("mode", ["uncertain", "receipt_timeout", "operation_only", "timeout"])
def test_uncertain_never_reimports(setup, mode):
    fake, result, vault = setup()
    approve(result, vault)
    fake.mode = mode
    if "timeout" in mode:
        with pytest.raises(RuntimeError, match="timeout"):
            w.publish(result["job"])
    else:
        w.publish(result["job"])
    outcome = w.publish(result["job"])
    assert fake.imports == 1
    assert outcome["status"] == ("publish_uncertain" if mode == "timeout" else "verified")
    if mode == "timeout":
        with pytest.raises(WorkflowError, match="不能重导入"):
            w.verify(result["job"])


def test_delete_crash_reconciles_without_second_delete(setup):
    fake, result, vault = setup(delete_verified=True)
    approve(result, vault)
    w.publish(result["job"])
    fake.delete_timeout = True
    with pytest.raises(RuntimeError, match="delete timeout"):
        w.cleanup(result["job"], True)
    # 同 URL 的其他收藏不影响按精确 ID 核验删除。
    fake.cards["copy"] = card("copy", url="https://example.org/a")
    fake.archived.add("copy")
    assert w.cleanup(result["job"], True)["status"] == "cleaned"
    assert fake.deletes == 1


@pytest.mark.parametrize(
    "mutation", ["note", "source", "approved", "remote", "outline", "soota-note", "old-node", "new-child"]
)
def test_mutation_prevents_delete(setup, mutation):
    fake, result, vault = setup(delete_verified=True)
    approve(result, vault)
    w.publish(result["job"])
    folder = Path(result["job"])
    if mutation == "note":
        (vault / "Knowledge/Topic a.md").write_text("human edit")
    elif mutation == "source":
        Path(result["sources"][0]["source_path"]).write_text("changed source")
    elif mutation in {"approved", "outline"}:
        (folder / (mutation + ".json")).write_text("{}")
    elif mutation == "remote":
        fake.cards["a"]["card"]["content"] = "remote changed"
    elif mutation == "soota-note":
        (Path(result["handoffs"]["a"]["bundle"]) / "note.md").write_text("changed analysis")
    elif mutation == "old-node":
        fake.nodes[0]["note"] = "changed old content"
    else:
        fake.nodes[-1]["children"][0]["children"] = []
    with pytest.raises(WorkflowError):
        w.cleanup(result["job"], True)
    assert fake.deletes == 0


def test_existing_different_note_and_duplicate_theme_refused(setup):
    fake, result, vault = setup()
    approve(result, vault)
    target = vault / "Knowledge/Topic a.md"
    target.parent.mkdir()
    target.write_text("handwritten")
    with pytest.raises(WorkflowError, match="独立审阅合并"):
        w.publish(result["job"])
    assert target.read_text() == "handwritten" and fake.imports == 0


def test_duplicate_mubu_root_refused_before_note_write(setup):
    fake, result, vault = setup()
    approve(result, vault)
    fake.nodes[0]["text"] = "Topic a"
    with pytest.raises(WorkflowError, match="同名主题"):
        w.publish(result["job"])
    assert not (vault / "Knowledge").exists() and fake.imports == 0


def test_cross_source_submission_refused_but_merged_note_accepted(setup):
    _fake, result, vault = setup([card("a"), card("b")])
    review = review_for(result, vault)
    path = Path(result["job"]) / "review.json"
    broken = deepcopy(review)
    binding = result["handoffs"]["b"]
    broken["sources"][0]["submission"]["note_markdown"] = f"[other](<{binding['context']}#para-1>)"
    write(path, broken)
    with pytest.raises(WorkflowError, match="其他来源"):
        w.submit(result["job"], path)
    review["notes"][0]["markdown"] += "\n" + review["notes"][1]["markdown"]
    review["notes"][0]["body_sha256"] = sha(review["notes"][0]["markdown"])
    review["notes"][0]["source_ids"] = ["a", "b"]
    review["notes"] = review["notes"][:1]
    write(path, review)
    assert w.submit(result["job"], path)["completed_source_ids"] == ["a", "b"]


def test_used_item_must_complete_and_frozen_resume(setup):
    fake, result, vault = setup()
    review = review_for(result, vault)
    path = Path(result["job"]) / "review.json"
    write(path, review)
    fake.incomplete = {"item-0"}
    with pytest.raises(WorkflowError, match="尚未完成"):
        w.submit(result["job"], path)
    assert not (Path(result["job"]) / "approved.json").exists()
    altered = deepcopy(review)
    altered["sources"][0]["review_notes"] = "different review"
    write(path, altered)
    with pytest.raises(WorkflowError, match="文件已修改"):
        w.submit(result["job"], path)
    write(path, review)
    fake.incomplete = set()
    w.submit(result["job"], path)
    count = len(fake.calls)
    w.submit(result["job"], path)
    assert len(fake.calls) == count


def test_lock_blocks_same_process_other_thread(setup):
    _fake, result, _vault = setup()
    failures = []
    with lock(Path(result["job"]) / ".lock"):

        def invoke():
            try:
                w.status(result["job"])
            except WorkflowError as exc:
                failures.append(str(exc))

        thread = threading.Thread(target=invoke)
        thread.start()
        thread.join()
    assert failures and "写入者" in failures[0]


def test_parent_node_import_and_configured_auth(setup):
    fake, result, vault = setup(mubu_parent="old-root", mubu_auth="password")
    approve(result, vault)
    assert w.publish(result["job"])["status"] == "verified"
    assert len(fake.nodes) == 1 and len(fake.nodes[0]["children"]) == 1


def native_bundle(path, *, target="123456", row_id=None, operation="opencli.twitter.thread"):
    path.mkdir()
    write(
        path / "data.json",
        [
            {
                "id": row_id or target,
                "url": f"https://x.com/example/status/{row_id or target}",
                "text": "Synthetic original text",
                "has_media": False,
            }
        ],
    )
    entry = artifact(path, "data.json", "data")
    entry["provider"] = "opencli"
    write(
        path / "manifest.json",
        {
            "schema_version": 2,
            "source": {
                "platform": "native",
                "kind": "query",
                "id": "synthetic-query",
                "url": operation,
                "canonical_url": operation,
            },
            "content": None,
            "artifacts": [entry],
        },
    )
    return path


def test_native_supplement_exact_target_json_and_missing_control(setup, tmp_path):
    bundle = native_bundle(tmp_path / "external")
    _fake, result, vault = setup(
        [
            card("a", status="description_only", url="https://twitter.com/example/status/123456"),
            card("missing", status="description_only"),
        ],
        source_bundles={"a": str(bundle)},
        delete_verified=True,
    )
    source = result["sources"][0]
    assert source["content_status"] == "description_only" and source["origin"] == "soota_bundle"
    assert Path(source["source_path"]).read_bytes() == (bundle / "data.json").read_bytes()
    approve(result, vault)
    w.publish(result["job"])
    assert w.cleanup(result["job"], True)["retained_ids"] == ["missing"]


@pytest.mark.parametrize("issue", ["wrong-id", "wrong-operation", "tampered-data", "no-text", "wrong-url"])
def test_native_bundle_cannot_impersonate_target(setup, tmp_path, issue):
    bundle = native_bundle(
        tmp_path / "external",
        row_id="654321" if issue == "wrong-id" else None,
        operation="opencli.twitter.search" if issue == "wrong-operation" else "opencli.twitter.thread",
    )
    if issue == "tampered-data":
        (bundle / "data.json").write_text("[]")
    if issue in {"no-text", "wrong-url"}:
        data = json.loads((bundle / "data.json").read_text())
        data[0]["text" if issue == "no-text" else "url"] = (
            "" if issue == "no-text" else "https://x.com/other/status/123456"
        )
        write(bundle / "data.json", data)
        manifest = json.loads((bundle / "manifest.json").read_text())
        entry = artifact(bundle, "data.json", "data")
        entry["provider"] = "opencli"
        manifest["artifacts"] = [entry]
        write(bundle / "manifest.json", manifest)
    with pytest.raises(WorkflowError):
        setup(
            [card("a", status="description_only", url="https://x.com/example/status/123456")],
            source_bundles={"a": str(bundle)},
        )


def test_external_source_change_blocks_cleanup(setup, tmp_path):
    bundle = native_bundle(tmp_path / "external")
    fake, result, vault = setup(
        [card("a", status="description_only", url="https://x.com/example/status/123456")],
        source_bundles={"a": str(bundle)},
        delete_verified=True,
    )
    approve(result, vault)
    w.publish(result["job"])
    (bundle / "data.json").write_text("changed")
    with pytest.raises(WorkflowError, match="文件已修改"):
        w.cleanup(result["job"], True)
    assert fake.deletes == 0


def test_standard_body_bundle_identity_and_original_bytes(setup, tmp_path):
    bundle = tmp_path / "article"
    bundle.mkdir()
    source = {
        "platform": "web",
        "kind": "article",
        "id": "synthetic",
        "url": "https://example.org/a",
        "canonical_url": "https://example.org/a",
    }
    body = " Original body\r\n\nDetailed evidence.\n"
    (bundle / "body.md").write_bytes(body.encode())
    (bundle / "context.md").write_text('<a id="para-original"></a>\nOriginal body')
    write(
        bundle / "manifest.json",
        {
            "schema_version": 2,
            "source": source,
            "content": {"source": source, "scope": "unknown", "blocks": [{"text": body}], "body_markdown": body},
            "context_fingerprint": sha((bundle / "context.md").read_bytes()),
            "artifacts": [artifact(bundle, "body.md", "body"), artifact(bundle, "context.md", "context")],
        },
    )
    _fake, result, vault = setup([card("a", status="description_only")], source_bundles={"a": str(bundle)})
    assert Path(result["sources"][0]["source_path"]).read_bytes() == body.encode()
    approve(result, vault)
    assert w.publish(result["job"])["status"] == "verified"


def test_crash_after_intent_before_dispatch_does_not_replay(setup, monkeypatch):
    fake, result, vault = setup()
    approve(result, vault)

    def interrupted(tool, args, **kwargs):
        if tool == "mubu" and "--execute" in args:
            raise KeyboardInterrupt()
        return fake(tool, args, **kwargs)

    monkeypatch.setattr(w, "run_json", interrupted)
    with pytest.raises(KeyboardInterrupt):
        w.publish(result["job"])
    monkeypatch.setattr(w, "run_json", fake)
    assert w.publish(result["job"])["status"] == "publish_uncertain"
    assert fake.imports == 0


def test_delete_unknown_with_target_still_present_is_read_only(setup, monkeypatch):
    fake, result, vault = setup(delete_verified=True)
    approve(result, vault)
    w.publish(result["job"])
    dispatched = []

    def interrupted(tool, args, **kwargs):
        if tool == "cubox" and args[0] == "delete" and "--dry-run" not in args:
            dispatched.append(args)
            raise RuntimeError("unconfirmed")
        return fake(tool, args, **kwargs)

    monkeypatch.setattr(w, "run_json", interrupted)
    with pytest.raises(RuntimeError, match="unconfirmed"):
        w.cleanup(result["job"], True)
    outcome = w.cleanup(result["job"], True)
    assert outcome["status"] == "cleanup_uncertain" and outcome["cleanup"]["remaining_ids"] == ["a"]
    assert len(dispatched) == 1 and fake.deletes == 0


def test_same_body_deduplicates_task_inputs_without_losing_card_identity(setup):
    fake, result, vault = setup([card("a", content="Same text"), card("b", content="Same text")])
    assert len(fake.items) == 1
    assert result["handoffs"]["a"] == result["handoffs"]["b"]
    approve(result, vault)
    assert w.publish(result["job"])["completed_source_ids"] == ["a", "b"]


def test_separate_evidence_keeps_audit_paths_out_of_knowledge(setup):
    _fake, result, vault = setup()
    review = review_for(result, vault)
    note = review["notes"][0]
    note["markdown"] = "# Topic a\n\nReadable knowledge.\n\n[来源](https://example.org/a)\n"
    note["body_sha256"] = sha(note["markdown"])
    note["evidence"] = {"a": [result["handoffs"]["a"]["context"] + "#para-0"]}
    path = Path(result["job"]) / "review.json"
    write(path, review)
    w.submit(result["job"], path)
    w.publish(result["job"])
    actual = (vault / "Knowledge/Topic a.md").read_text()
    assert actual == note["markdown"] and result["job"] not in actual and "para-0" not in actual
    frozen = json.loads((Path(result["job"]) / "approved.json").read_text())
    assert frozen["notes"][0]["evidence"] == note["evidence"]


def test_separate_evidence_cannot_reference_another_source(setup):
    _fake, result, vault = setup([card("a"), card("b")])
    review = review_for(result, vault)
    note = review["notes"][0]
    note["markdown"] = "# Topic a\n\nReadable knowledge.\n"
    note["body_sha256"] = sha(note["markdown"])
    note["evidence"] = {"a": [result["handoffs"]["b"]["context"] + "#para-1"]}
    path = Path(result["job"]) / "review.json"
    write(path, review)
    with pytest.raises(WorkflowError, match="其他来源"):
        w.submit(result["job"], path)
