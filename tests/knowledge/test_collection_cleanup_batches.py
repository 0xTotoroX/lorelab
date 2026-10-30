"""真实任务文件与模拟 CLI 验证分批、明确恢复和失败停批，不访问账号。"""

import json
from pathlib import Path

import pytest

from lorelab.knowledge import collection as c
from lorelab.knowledge.workflow_state import WorkflowError

from .support import card
from .test_collection import authorization, review_for, submit
from .test_collection import setup as setup  # noqa: PLC0414 - 显式导入 pytest fixture。


def prepared(setup, size=5):
    start, fake, target, _material, source = setup
    sources = [{**source, "id": str(1001 + i)} for i in range(size)]
    for entry in sources:
        fake.cards[entry["id"]] = card(entry["id"], url=source["url"])
    result = start(sources)
    submit(result, review_for(result, target))
    authorization(result, ids=[s["id"] for s in sources])
    return result, fake, target


def writes(fake):
    return [args[args.index("--id") + 1].split(",") for _, args, _ in fake.calls
            if args[0] == "delete" and "--dry-run" not in args]


def test_small_trial_then_explicit_resume_preserves_original_intent(setup):
    result, fake, _target = prepared(setup)
    first = c.cleanup(result["job"], True, batch_size=2, max_batches=1)
    assert first["status"] == "cleanup_paused" and first["ok"]
    intent = Path(result["job"]) / "cleanup-intent.json"
    original = intent.read_bytes()
    assert c.cleanup(result["job"], True)["status"] == "cleanup_paused"
    assert writes(fake) == [["1001", "1002"]]
    final = c.cleanup(result["job"], True, resume=True, batch_size=2)
    assert final["status"] == "cleaned" and final["cleanup"]["remaining_ids"] == []
    assert writes(fake) == [["1001", "1002"], ["1003", "1004"], ["1005"]]
    assert intent.read_bytes() == original and "9001" in fake.cards
    assert len(final["cleanup"]["attempts"]) == 2
    assert len({b["receipt"] for b in final["cleanup"]["batches"]}) == 3
    for entry in final["cleanup"]["batches"]:
        assert entry["status"] == "verified"
        assert (Path(result["job"]) / entry["receipt"]).is_file()
        assert (Path(result["job"]) / entry["intent"]).stat().st_mode & 0o777 == 0o600


def test_partial_timeout_stops_and_resume_only_sends_remaining(setup, monkeypatch):
    result, fake, _target = prepared(setup)
    real = fake._run
    failed = False

    def partial(tool, args, receipt):
        nonlocal failed
        if args[0] == "delete" and "--dry-run" not in args and not failed:
            failed = True
            fake.deletes += 1
            fake.cards.pop("1001")
            raise RuntimeError("simulated partial timeout")
        return real(tool, args, receipt)

    monkeypatch.setattr(fake, "_run", partial)
    with pytest.raises(RuntimeError, match="partial timeout"):
        c.cleanup(result["job"], True, batch_size=2)
    state = c.status(result["job"])
    assert state["status"] == "cleanup_uncertain"
    assert state["cleanup"]["absent_ids"] == ["1001"]
    assert len(writes(fake)) == 1
    assert c.cleanup(result["job"], True)["status"] == "cleanup_uncertain"
    assert len(writes(fake)) == 1
    final = c.cleanup(result["job"], True, resume=True, batch_size=2)
    assert final["status"] == "cleaned"
    assert writes(fake)[1:] == [["1002", "1003"], ["1004", "1005"]]


def test_failure_after_one_successful_batch_never_replays_verified_batch(setup, monkeypatch):
    result, fake, _target = prepared(setup)
    real = fake._run

    def fail_second(tool, args, receipt):
        if args[0] == "delete" and "--dry-run" not in args and fake.deletes == 1:
            fake.deletes += 1
            raise RuntimeError("synthetic HTTP failure")
        return real(tool, args, receipt)

    monkeypatch.setattr(fake, "_run", fail_second)
    with pytest.raises(RuntimeError, match="HTTP"):
        c.cleanup(result["job"], True, batch_size=2)
    assert writes(fake) == [["1001", "1002"], ["1003", "1004"]]
    monkeypatch.setattr(fake, "_run", real)
    assert c.cleanup(result["job"], True, resume=True, batch_size=2)["status"] == "cleaned"
    assert writes(fake)[2:] == [["1003", "1004"], ["1005"]]


@pytest.mark.parametrize("change", ["article", "protected", "identity", "authorization", "intent"])
def test_resume_rechecks_frozen_delivery_identity_and_scope(setup, change):
    result, fake, target = prepared(setup)
    c.cleanup(result["job"], True, batch_size=1, max_batches=1)
    if change == "article":
        (target / "article.md").write_text("Human edit")
    elif change == "protected":
        fake.folder_rows = [{"id": "github", "name": "GitHub", "parent_id": None}]
        fake.cards["1002"]["card"]["folder"] = {"id": "github", "name": "GitHub"}
    elif change == "identity":
        fake.cards["1002"]["card"]["url"] = "https://x.com/changed/status/9999"
    else:
        state = c.status(result["job"])
        path = Path(result["job"]) / (state["authorization"] if change == "authorization" else "cleanup-intent.json")
        path.write_text("{}")
    with pytest.raises(WorkflowError):
        c.cleanup(result["job"], True, resume=True, batch_size=2)
    assert writes(fake) == [["1001"]]
    if change not in {"authorization", "intent"}:
        assert c.status(result["job"])["status"] == "cleanup_blocked"
        assert not c.status(result["job"])["ok"]


def test_human_change_during_preview_stops_before_delete(setup, monkeypatch):
    result, fake, _target = prepared(setup)
    real = fake._run

    def edit(tool, args, receipt):
        value = real(tool, args, receipt)
        if args[0] == "delete" and "--dry-run" in args and "batch-0001" in str(receipt):
            fake.cards["1001"]["card"]["title"] = "Human updated title"
        return value

    monkeypatch.setattr(fake, "_run", edit)
    with pytest.raises(WorkflowError, match="人工"):
        c.cleanup(result["job"], True, batch_size=2)
    assert not writes(fake)
    assert c.status(result["job"])["status"] == "cleanup_blocked"


def test_missing_non_target_stops_subsequent_batches(setup, monkeypatch):
    result, fake, _target = prepared(setup)
    real = fake._run

    def remove_other(tool, args, receipt):
        value = real(tool, args, receipt)
        if args[0] == "delete" and "--dry-run" not in args:
            fake.cards.pop("9001")
        return value

    monkeypatch.setattr(fake, "_run", remove_other)
    with pytest.raises(WorkflowError, match="非本批"):
        c.cleanup(result["job"], True, batch_size=2)
    assert writes(fake) == [["1001", "1002"]]


def test_preservation_failure_cannot_be_cleared_by_read_only_or_empty_resume(setup, monkeypatch):
    result, fake, _target = prepared(setup, size=2)
    real = fake._run
    original = fake.cards["9001"]

    def remove_other(tool, args, receipt):
        value = real(tool, args, receipt)
        if args[0] == "delete" and "--dry-run" not in args:
            fake.cards.pop("9001")
        return value

    monkeypatch.setattr(fake, "_run", remove_other)
    with pytest.raises(WorkflowError):
        c.cleanup(result["job"], True, batch_size=2)
    for options in ({}, {"execute": True, "resume": True}):
        with pytest.raises(WorkflowError, match="保全"):
            c.cleanup(result["job"], **options)
        assert not c.status(result["job"])["ok"]
    fake.cards["9001"] = original
    assert c.cleanup(result["job"])["status"] == "cleaned"
    assert writes(fake) == [["1001", "1002"]]


def test_between_batch_change_is_not_accepted_as_new_baseline(setup, monkeypatch):
    result, fake, _target = prepared(setup)
    real = fake._run

    def change_between(tool, args, receipt):
        value = real(tool, args, receipt)
        if args[0] == "delete" and "--dry-run" in args and "batch-0002" in str(receipt):
            fake.cards["9001"]["card"]["title"] = "Unrelated human update"
        return value

    monkeypatch.setattr(fake, "_run", change_between)
    with pytest.raises(WorkflowError, match="人工"):
        c.cleanup(result["job"], True, batch_size=2)
    assert writes(fake) == [["1001", "1002"]]
    assert c.status(result["job"])["status"] == "cleanup_blocked"


@pytest.mark.parametrize("options", [
    {"batch_size": 0}, {"batch_size": 101}, {"batch_size": True},
    {"max_batches": 0}, {"max_batches": True}, {"resume": True},
])
def test_invalid_batch_options_are_read_only(setup, options):
    result, fake, _target = prepared(setup)
    before = len(fake.calls)
    with pytest.raises(WorkflowError):
        c.cleanup(result["job"], **options)
    assert len(fake.calls) == before


def test_legacy_uncertain_intent_resumes_without_rewriting_old_receipts(setup):
    result, fake, _target = prepared(setup)
    from lorelab.knowledge.workflow_state import read_json, save, seal

    c.verify(result["job"])
    job = Path(result["job"])
    state = read_json(job / "job.json")
    intent = {"ids": [str(x) for x in range(1001, 1006)], "lookup_urls": [],
              "authorization_sha256": state["sealed"][state["authorization"]],
              "review_sha256": state["ready"]["review_sha256"]}
    seal(job, state, "cleanup-intent.json", intent)
    state["cleanup"] = {**intent, "status": "uncertain"}
    state["status"] = "cleanup_uncertain"
    save(job, state)
    old = job / "receipts/collection-cleanup-execute.json"
    old.write_text(json.dumps({"legacy": True}))
    original = old.read_bytes()
    assert c.cleanup(str(job), True, resume=True, batch_size=2)["status"] == "cleaned"
    assert old.read_bytes() == original
    assert writes(fake) == [["1001", "1002"], ["1003", "1004"], ["1005"]]
