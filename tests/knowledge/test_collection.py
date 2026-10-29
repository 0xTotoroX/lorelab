"""集合账本的真实文件回读、固定范围和一次删除恢复；仅替换 CLI 进程边界。"""

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from lorelab.cli import main
from lorelab.knowledge import collection as c
from lorelab.knowledge.workflow_state import WorkflowError, lock

from .support import FakeCLI, card, sha, write


class CollectionCLI(FakeCLI):
    def _run(self, tool, args, receipt):
        if tool == "cubox" and args[:2] == ["card", "list"] and "--url" not in args:
            assert "--all" in args
            return [deepcopy(value["card"]) for key, value in self.cards.items()
                    if value["status"] == "ok" and (key in self.archived) == ("--archived" in args)]
        return super()._run(tool, args, receipt)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "locks"))
    material = tmp_path / "materials"
    material.mkdir()
    target = tmp_path / "knowledge"
    target.mkdir()
    raw = material / "raw.jsonl"
    raw.write_text('{"id":"2001","text":"Full captured text"}\n')
    body = material / "body.txt"
    body.write_text("Full captured text; further context and linked content.\n")
    source = {"id": "1001", "status_id": "2001", "url": "https://x.com/example/status/2001",
              "availability": "collected", "text_file": str(body),
              "raw_files": [{"path": str(raw), "sha256": sha(raw.read_bytes())}]}
    manifest = material / "manifest.json"
    value = {"schema_version": 1, "destination": str(target), "sources": [source]}
    fake = CollectionCLI([card("1001", url=source["url"]), card("9001", url="https://github.com/example/repo")])
    monkeypatch.setattr(c.runtime, "run_json", fake)

    def start(sources=None, edit=None):
        content = deepcopy(value)
        if sources is not None:
            content["sources"] = sources
        if edit:
            edit(content)
        write(manifest, content)
        return c.prepare(manifest, tmp_path / "jobs")

    return start, fake, target, material, source


def review_for(result, target, *, decision="processed", outputs=None):
    template = json.loads(Path(result["review_template"]).read_text())
    article = target / "article.md"
    article.write_text("# Synthetic article\n\nActual delivered text from captured source.\n")
    for entry in template["sources"]:
        entry.update(read_sha256=entry["source_sha256"], decision=decision, strategy="按价值综合整理",
                     rationale="保留可复用的观点与证据", coverage="原帖与链接逐项审阅", complete=decision == "processed",
                     gaps=[] if decision == "processed" else ["显式保留"],
                     outputs=outputs if outputs is not None else [
                         {"kind": "article", "path": article.name, "sha256": sha(article.read_bytes())}])
    return template


def submit(result, value):
    path = Path(result["job"]) / "submitted.json"
    write(path, value)
    return c.submit(result["job"], path)


def authorization(result, ids=None, unavailable=None, no_yield=None):
    path = Path(result["job"]) / "authorization-input.json"
    value = {"schema_version": 1, "reason": "合成测试明确授权，真实账号未访问",
             "delete_ids": ids or ["1001"], "unavailable_ids": unavailable or []}
    if no_yield is not None:
        value["no_yield_ids"] = no_yield
    write(path, value)
    return c.authorize(result["job"], path)


def no_yield_review(result):
    value = json.loads(Path(result["review_template"]).read_text())
    for entry in value["sources"]:
        entry.update(read_sha256=entry["source_sha256"], decision="reviewed-no-yield", complete=True,
                     strategy="实读后留存无新知识判断", rationale="只有重复感叹，不凑文章",
                     coverage="已读全部文字；无关键媒体、引用或未取得的内容。", gaps=[], outputs=[],
                     no_yield_reason="没有具体观点、回复或可沉淀的新知识。")
    return value


def unavailable(result, material, code="NotFound"):
    proof = material / "unavailable.json"
    write(proof, {"id": "2001", "error": code})
    entry = json.loads(Path(result["review_template"]).read_text())["sources"][0]
    entry.update(decision="confirmed-unavailable", strategy="保留远端不可用证据", rationale="源站返回失败",
                 coverage="尚无完整正文，未总结", complete=False, gaps=["正文不可用"], outputs=[],
                 unavailable_evidence={"code": code, "url": "https://x.com/example/status/2001",
                                       "reason": "远端原始错误", "observed_at": "2026-10-29T10:00:00+08:00",
                                       "files": [{"path": str(proof), "sha256": sha(proof.read_bytes())}]})
    return {"schema_version": 1, "sources": [entry]}


def test_full_chain_real_files_multiple_outputs_and_no_model(setup):
    start, fake, target, _material, _source = setup
    result = start()
    assert not fake.calls  # prepare 离线，不要求 Soota job。
    fake.cards["9002"] = card("9002", url="https://github.com/another/tool")
    value = review_for(result, target)
    second = target / "second.md"
    second.write_text("# Second article\nAdditional verified text")
    value["sources"][0]["outputs"] += [
        {"kind": "article", "path": "second.md", "sha256": sha(second.read_bytes())},
        {"kind": "repository", "url": "https://github.com/example/repo", "cubox_id": "9001"},
        {"kind": "repository", "url": "https://github.com/another/tool", "cubox_id": "9002"}]
    submit(result, value)
    ready = c.verify(result["job"])
    assert ready["ok"] and ready["ready"]["ready"]
    assert len(ready["ready"]["verification"]["articles"]) == 2
    assert len(ready["ready"]["verification"]["repositories"]) == 2
    authorization(result)
    assert c.cleanup(result["job"])["cleanup_preview"]["eligible_ids"] == ["1001"]
    assert not fake.deletes
    assert c.cleanup(result["job"], True)["status"] == "cleaned"
    assert c.cleanup(result["job"], True)["status"] == "cleaned"
    assert fake.deletes == 1 and {"9001", "9002"} <= set(fake.cards)
    assert all(tool == "cubox" for tool, _, _ in fake.calls)
    assert any("--archived" in args for _, args, _ in fake.calls)
    assert (Path(result["job"]) / "job.json").stat().st_mode & 0o777 == 0o600


def test_shared_x_evidence_for_distinct_cubox_ids(setup):
    start, fake, target, _material, source = setup
    second = {**source, "id": "1002"}
    fake.cards["1002"] = card("1002", url=source["url"])
    result = start([source, second])
    assert result["sources"][0]["text_sha256"] == result["sources"][1]["text_sha256"]
    value = review_for(result, target)
    submit(result, {"schema_version": 1, "sources": value["sources"][:1]})
    authorization(result)
    assert not c.ready(result["job"])["ok"]
    with pytest.raises(WorkflowError, match="全批"):
        c.cleanup(result["job"], True)
    submit(result, {"schema_version": 1, "sources": value["sources"][1:]})
    assert c.ready(result["job"])["ok"]
    cleaned = c.cleanup(result["job"], True)
    assert cleaned["cleanup"]["ids"] == ["1001"]
    assert cleaned["cleanup"]["retained_ids"] == ["1002"] and "1002" in fake.cards


@pytest.mark.parametrize("mutation,match", [
    (lambda v: v["sources"].append(deepcopy(v["sources"][0])), "重复 Cubox"),
    (lambda v: v["sources"][0].update(status_id="8888"), "status ID"),
    (lambda v: v["sources"][0].update(url="https://github.com/example/repo"), "status ID"),
    (lambda v: v["sources"][0].update(id="--injection"), "数字字符串"),
    (lambda v: v["sources"][0]["raw_files"][0].update(sha256="0" * 64), "文件已修改"),
    (lambda v: v.update(materials_root="/does-not-exist"), "materials_root"),
])
def test_bad_source_contract(setup, mutation, match):
    start, _fake, _target, _material, _source = setup
    with pytest.raises(WorkflowError, match=match):
        start(edit=mutation)


def test_missing_cannot_fake_complete_or_bypass_whole_collection(setup):
    start, fake, target, _material, source = setup
    result = start([{**source, "availability": "missing", "text_file": None}])
    value = review_for(result, target)
    with pytest.raises(WorkflowError, match="缺失来源"):
        submit(result, value)
    value["sources"][0].update(decision="retain", complete=False, outputs=[], gaps=["缺少正文"])
    submit(result, value)
    assert not c.ready(result["job"])["ok"]
    with pytest.raises(WorkflowError, match="retain"):
        authorization(result)
    assert not fake.deletes


def test_unavailable_requires_evidence_and_separate_authorization(setup):
    start, fake, _target, material, source = setup
    result = start([{**source, "availability": "missing", "text_file": None}])
    value = unavailable(result, material)
    broken = deepcopy(value)
    broken["sources"][0]["complete"] = True
    with pytest.raises(WorkflowError, match="失效不能"):
        submit(result, broken)
    broken = deepcopy(value)
    broken["sources"][0].pop("unavailable_evidence")
    with pytest.raises(WorkflowError, match="单独的证据"):
        submit(result, broken)
    submit(result, value)
    assert c.ready(result["job"])["ok"]
    with pytest.raises(WorkflowError, match="unavailable_ids"):
        authorization(result)
    authorization(result, unavailable=["1001"])
    assert c.cleanup(result["job"], True)["status"] == "cleaned"
    assert fake.deletes == 1
    approved = json.loads(next((Path(result["job"]) / "reviews").glob("*.json")).read_text())
    assert not approved["complete"] and approved["gaps"] and not approved["outputs"]


@pytest.mark.parametrize("code", ["AuthorizationError", "Timeout", "Forbidden"])
def test_authentication_failure_is_never_unavailability(setup, code):
    start, _fake, _target, material, _source = setup
    result = start()
    with pytest.raises(WorkflowError, match="AuthorizationError"):
        submit(result, unavailable(result, material, code))


@pytest.mark.parametrize("path", ["../escape.md", "/tmp/escape.md", "AGENTS.md", ".hidden/file.md"])
def test_output_path_cannot_escape_target(setup, path):
    start, _fake, target, _material, _source = setup
    result = start()
    value = review_for(result, target, outputs=[{"kind": "article", "path": path, "sha256": "0" * 64}])
    with pytest.raises(WorkflowError):
        submit(result, value)


def test_output_symlink_and_changed_files_rejected(setup, tmp_path):
    start, _fake, target, _material, _source = setup
    result = start()
    value = review_for(result, target)
    submit(result, value)
    (target / "article.md").write_text("Human edit")
    with pytest.raises(WorkflowError, match="文件已修改"):
        c.ready(result["job"])
    outside = tmp_path / "outside.md"
    outside.write_text("Elsewhere")
    (target / "article.md").unlink()
    (target / "article.md").symlink_to(outside)
    with pytest.raises(WorkflowError, match="符号链接"):
        c.ready(result["job"])


@pytest.mark.parametrize("mode", ["missing", "mismatch", "mention", "source_id"])
def test_repository_requires_real_card_readback(setup, mode):
    start, fake, target, _material, _source = setup
    result = start()
    output = {"kind": "repository", "url": "https://github.com/example/repo", "cubox_id": "9001"}
    if mode == "missing":
        fake.cards.pop("9001")
    if mode == "mismatch":
        fake.cards["9001"]["card"]["url"] = "https://github.com/example/other"
    if mode == "mention":
        output["url"] = "https://example.org/posts/github-project"
    if mode == "source_id":
        output["cubox_id"] = "1001"
    with pytest.raises(WorkflowError):
        submit(result, review_for(result, target, outputs=[output]))


def test_repository_removed_after_review_blocks_cleanup(setup):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target, outputs=[
        {"kind": "repository", "url": "https://github.com/example/repo", "cubox_id": "9001"}]))
    authorization(result)
    fake.cards.pop("9001")
    with pytest.raises(WorkflowError, match="真实回读"):
        c.cleanup(result["job"], True)
    assert not fake.deletes


def test_source_material_mutation_and_concurrent_lock_rejected(setup):
    start, _fake, _target, material, _source = setup
    result = start()
    with lock(Path(result["job"]) / ".lock"), pytest.raises(WorkflowError, match="另一个操作"):
        c.status(result["job"])
    (material / "body.txt").write_text("Changed input")
    with pytest.raises(WorkflowError, match="文件已修改"):
        c.status(result["job"])


def test_feedback_version_evidence_and_rollback(setup):
    start, _fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    path = Path(result["job"]) / "feedback-input.json"
    value = {"schema_version": 1, "base_version": 0, "strategy": "策略一",
             "rationale": "真实文章回读支持这次调整", "source_ids": ["1001"], "rollback_to": None}
    write(path, value)
    assert c.feedback(result["job"], path)["strategy_version"] == 1
    with pytest.raises(WorkflowError, match="版本已改变"):
        c.feedback(result["job"], path)
    write(path, {**value, "base_version": 1, "strategy": "策略二"})
    c.feedback(result["job"], path)
    write(path, {**value, "base_version": 2, "rollback_to": 1})
    last = c.feedback(result["job"], path)
    assert last["strategy_version"] == 3
    record = json.loads((Path(result["job"]) / last["feedback"][-1]).read_text())
    assert record["rollback_to"] == 1 and record["evidence"]["1001"]["sha256"]
    assert record["verification"]["articles"]


def test_no_authorization_and_wrong_id_never_delete(setup):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    with pytest.raises(WorkflowError, match="未声明删除授权"):
        c.cleanup(result["job"], True)
    with pytest.raises(WorkflowError, match="越界"):
        authorization(result, ["9001"])
    fake.cards["1001"]["card"]["url"] = "https://x.com/example/status/9999"
    with pytest.raises(WorkflowError, match="status ID"):
        c.verify(result["job"])
    assert not fake.deletes


def test_github_folder_protection(setup):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    authorization(result)
    fake.folder_rows = [{"id": "github", "name": "GitHub", "parent_id": None}]
    fake.cards["1001"]["card"]["folder"] = {"id": "github", "name": "GitHub"}
    with pytest.raises(WorkflowError, match="保护"):
        c.cleanup(result["job"], True)
    assert not fake.deletes


def test_timeout_after_delete_is_read_only_on_resume(setup):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    authorization(result)
    fake.delete_timeout = True
    with pytest.raises(RuntimeError, match="timeout"):
        c.cleanup(result["job"], True)
    assert c.status(result["job"])["cleanup"]["status"] == "uncertain"
    assert c.cleanup(result["job"], True)["status"] == "cleaned"
    assert fake.deletes == 1
    with pytest.raises(WorkflowError, match="删除意图已冻结"):
        authorization(result)


def test_uncertain_remaining_archived_card_never_resends(setup, monkeypatch):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    authorization(result)
    real = fake._run

    def partial(tool, args, receipt):
        if args[0] == "delete" and "--dry-run" not in args:
            fake.deletes += 1
            fake.archived.add("1001")
            raise RuntimeError("Unknown write")
        return real(tool, args, receipt)

    monkeypatch.setattr(fake, "_run", partial)
    with pytest.raises(RuntimeError, match="Unknown write"):
        c.cleanup(result["job"], True)
    recovered = c.cleanup(result["job"], True)
    assert recovered["cleanup"]["remaining_ids"] == ["1001"] and not recovered["ok"]
    assert fake.deletes == 1


def test_remaining_card_with_changed_url_is_not_reported_deleted(setup, monkeypatch):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    authorization(result)
    real = fake._run

    def changed_url(tool, args, receipt):
        if args[0] == "delete" and "--dry-run" not in args:
            fake.deletes += 1
            fake.cards["1001"]["card"]["url"] = "https://x.com/renamed/status/2001"
            fake.archived.add("1001")
            return {"count": 0, "dry_run": False}
        return real(tool, args, receipt)

    monkeypatch.setattr(fake, "_run", changed_url)
    result = c.cleanup(result["job"], True)
    assert not result["ok"] and result["cleanup"]["remaining_ids"] == ["1001"]
    assert fake.deletes == 1


def test_cli_prepare_review_verify_status(setup, capsys):
    start, _fake, target, _material, _source = setup
    result = start()
    value = review_for(result, target)
    path = Path(result["job"]) / "input-review.json"
    write(path, value)
    for args in (["review", result["job"], "--file", str(path)],
                 ["verify", result["job"]], ["status", result["job"]]):
        assert main(["knowledge", "collection", *args]) == 0
        assert json.loads(capsys.readouterr().out)["ok"]


@pytest.mark.parametrize("mode", ["wrong_count", "wrong_id", "missing_cards"])
def test_dryrun_mismatch_never_deletes(setup, monkeypatch, mode):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    authorization(result)
    real = fake._run

    def mismatch(tool, args, receipt):
        value = real(tool, args, receipt)
        if args[0] == "delete" and "--dry-run" in args:
            if mode == "wrong_count":
                value["count"] = 99
            elif mode == "wrong_id":
                value["cards"] = [{"id": "9001"}]
            else:
                value.pop("cards")
        return value

    monkeypatch.setattr(fake, "_run", mismatch)
    with pytest.raises(WorkflowError, match="dry-run"):
        c.cleanup(result["job"], True)
    assert not fake.deletes


def test_final_recheck_blocks_changed_delivery(setup, monkeypatch):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    authorization(result)
    real = fake._run

    def change(tool, args, receipt):
        value = real(tool, args, receipt)
        if args[0] == "delete" and "--dry-run" in args:
            (target / "article.md").write_text("Changed during preview")
        return value

    monkeypatch.setattr(fake, "_run", change)
    with pytest.raises(WorkflowError, match="文件已修改"):
        c.cleanup(result["job"], True)
    assert not fake.deletes


def test_review_revisions_keep_history_and_feedback_rejects_unverified_outputs(setup):
    start, _fake, target, _material, _source = setup
    result = start()
    value = review_for(result, target)
    first = submit(result, value)
    value["sources"][0]["strategy"] = "修改后的逐帖策略"
    second = submit(result, value)
    assert first["review_files"]["1001"] != second["review_files"]["1001"]
    assert Path(first["review_files"]["1001"]).is_file()
    (target / "article.md").write_text("Later edit")
    path = Path(result["job"]) / "feedback-input.json"
    write(path, {"schema_version": 1, "base_version": 0, "strategy": "新策略", "rationale": "依据",
                 "source_ids": ["1001"], "rollback_to": None})
    with pytest.raises(WorkflowError, match="文件已修改"):
        c.feedback(result["job"], path)
    assert c.status(result["job"])["strategy_version"] == 0


def test_large_scope_shared_raw_file_checked_once_and_live_reads_inventory(setup, monkeypatch):
    start, fake, target, _material, source = setup
    sources = [{**source, "id": str(1001 + i)} for i in range(205)]
    for entry in sources:
        fake.cards[entry["id"]] = card(entry["id"], url=source["url"])
    checked = []
    real = c.check_file

    def count(path, fingerprint):
        checked.append(path.name)
        return real(path, fingerprint)

    monkeypatch.setattr(c, "check_file", count)
    result = start(sources)
    assert checked.count("raw.jsonl") == 1
    submit(result, review_for(result, target))
    assert c.verify(result["job"])["ok"]
    calls = [args for _, args, _ in fake.calls if args[:2] == ["card", "batch"]]
    assert not calls
    snapshots = [args for _, args, _ in fake.calls if args[:2] == ["card", "list"]]
    assert len(snapshots) == 2
    assert all("--all" in args for args in snapshots)
    assert sum("--archived" in args for args in snapshots) == 1


@pytest.mark.parametrize("url", ["https://twitter.com/i/web/status/2001",
                              "https://x.com/i/web/status/2001?s=20",
                              "https://mobile.twitter.com/example/status/2001"])
def test_web_status_alias_is_same_post(setup, url):
    start, fake, target, _material, source = setup
    fake.cards["1001"]["card"]["url"] = url
    result = start([{**source, "url": url}])
    submit(result, review_for(result, target))
    assert c.verify(result["job"])["ok"]


@pytest.mark.parametrize("url", ["https://x.com/search?q=2001", "https://x.com/i/web/status/2001/extra",
                              "https://x.com.evil.example/i/web/status/2001",
                              "https://x.com@evil.example/i/web/status/2001",
                              "https://x.com/i/web/status/9999"])
def test_status_alias_still_rejects_wrong_identity(url):
    with pytest.raises(WorkflowError, match="status ID"):
        c.x_status(url, "2001")


@pytest.mark.parametrize("mode", ["missing", "changed_url", "missing_folder", "duplicate"])
def test_large_scope_inventory_rejects_incomplete_or_changed_snapshot(setup, monkeypatch, mode):
    start, fake, target, _material, source = setup
    sources = [{**source, "id": str(1001 + i)} for i in range(101)]
    for entry in sources:
        fake.cards[entry["id"]] = card(entry["id"], url=source["url"])
    result = start(sources)
    submit(result, review_for(result, target))
    if mode == "missing":
        fake.cards.pop("1001")
    elif mode == "changed_url":
        fake.cards["1001"]["card"]["url"] = "https://x.com/example/status/9999"
    elif mode == "missing_folder":
        fake.cards["1001"]["card"].pop("folder")
    else:
        real = fake._run

        def duplicated(tool, args, receipt):
            value = real(tool, args, receipt)
            if args[:2] == ["card", "list"] and "--archived" not in args:
                value.append(deepcopy(value[0]))
            return value

        monkeypatch.setattr(fake, "_run", duplicated)
    with pytest.raises(WorkflowError):
        c.verify(result["job"])
    assert not fake.deletes


def test_large_repository_delivery_uses_current_inventory(setup):
    start, fake, target, _material, _source = setup
    result = start()
    outputs = []
    for i in range(101):
        key, url = str(9001 + i), f"https://github.com/example/repo{i}"
        fake.cards[key] = card(key, url=url)
        outputs.append({"kind": "repository", "url": url, "cubox_id": key})
    submit(result, review_for(result, target, outputs=outputs))
    assert not any(args[:2] == ["card", "batch"] for _, args, _ in fake.calls)
    fake.cards["9001"]["card"]["url"] = "https://github.com/example/changed"
    with pytest.raises(WorkflowError, match="URL 不符"):
        c.verify(result["job"])


def test_real_runtime_subprocess_cli_with_synthetic_cubox(setup, tmp_path):
    start, _fake, target, material, _source = setup
    start()  # 创建合成输入，下面从全新 CLI 进程准备独立任务。
    script = tmp_path / "fake_cubox.py"
    script.write_text('''import json, sys
from pathlib import Path
a = sys.argv[1:]
if a[:2] == ["card", "batch"]:
    ids = Path(a[a.index("--ids-file") + 1]).read_text().splitlines()
    items = [{"id": i, "status": "ok", "card": {"id": i, "url": "https://x.com/example/status/2001"}} for i in ids]
    print(json.dumps({"schema_version": 1, "kind": "cubox_card_batch", "items": items}))
else:
    raise SystemExit("Synthetic CLI rejects unexpected commands")
''')
    env = {**os.environ, "LORELAB_CUBOX_COMMAND": json.dumps([sys.executable, str(script)]),
           "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    for key in ("SOOTA_KNOWLEDGE_RUNTIME_FILE", "SOOTA_KNOWLEDGE_COMPONENTS_LOCK", "LORELAB_RUNTIME_FILE",
                "LORELAB_ROOT", "LOREHUB_RUNTIME_FILE", "LOREHUB_ROOT"):
        env.pop(key, None)

    def invoke(*args):
        value = subprocess.run([sys.executable, "-m", "lorelab.cli", "knowledge", "collection", *args],
                               env=env, text=True, capture_output=True, check=False, timeout=30)
        assert value.returncode == 0, value.stderr
        return json.loads(value.stdout)

    result = invoke("prepare", "--file", str(material / "manifest.json"), "--state-root", str(tmp_path / "process-jobs"))
    value = review_for(result, target)
    path = material / "process-review.json"
    write(path, value)
    invoke("review", result["job"], "--file", str(path))
    assert invoke("verify", result["job"])["ready"]["ready"]
    recovered = invoke("status", result["job"])
    assert recovered["ready"]["checked_at"] and recovered["review_files"]["1001"]


def test_no_yield_ready_and_explicit_cleanup_without_dummy_article(setup):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, no_yield_review(result))
    assert c.verify(result["job"])["ready"]["verification"] == {"articles": {}, "repositories": {}}
    assert not list(target.iterdir())
    with pytest.raises(WorkflowError, match="no_yield_ids"):
        authorization(result)  # 旧字段缺省为空，不能据此扩大到无产出来源。
    authorization(result, no_yield=["1001"])
    assert c.cleanup(result["job"])["cleanup_preview"]["eligible_ids"] == ["1001"]
    assert not fake.deletes
    assert c.cleanup(result["job"], True)["status"] == "cleaned"
    assert c.cleanup(result["job"], True)["status"] == "cleaned"
    assert fake.deletes == 1 and "9001" in fake.cards


@pytest.mark.parametrize("change", [
    {"source_sha256": None}, {"read_sha256": None}, {"read_sha256": "0" * 64},
    {"complete": False}, {"gaps": ["关键视频未读"]}, {"outputs": [{"kind": "article"}]},
    {"no_yield_reason": "  "}, {"coverage": ""},
])
def test_no_yield_requires_full_read_no_gaps_no_outputs_and_reason(setup, change):
    start, fake, _target, _material, _source = setup
    result = start()
    value = no_yield_review(result)
    value["sources"][0].update(change)
    with pytest.raises(WorkflowError):
        submit(result, value)
    assert c.status(result["job"])["pending_source_ids"] == ["1001"]
    assert not fake.calls


def test_no_yield_missing_source_and_feedback_are_rejected(setup):
    start, fake, _target, _material, source = setup
    result = start([{**source, "availability": "missing", "text_file": None}])
    with pytest.raises(WorkflowError, match="reviewed-no-yield"):
        submit(result, no_yield_review(result))
    assert not fake.deletes


def test_no_yield_cannot_supply_strategy_feedback(setup):
    start, _fake, _target, _material, _source = setup
    result = start()
    submit(result, no_yield_review(result))
    path = Path(result["job"]) / "feedback-input.json"
    write(path, {"schema_version": 1, "base_version": 0, "strategy": "调整策略", "rationale": "不能虚构交付证据",
                 "source_ids": ["1001"], "rollback_to": None})
    with pytest.raises(WorkflowError, match="真实交付"):
        c.feedback(result["job"], path)
    assert c.status(result["job"])["strategy_version"] == 0


@pytest.mark.parametrize("ids", [[], ["9001"], ["1001", "1001"]])
def test_no_yield_authorization_must_be_exact(setup, ids):
    start, fake, _target, _material, _source = setup
    result = start()
    submit(result, no_yield_review(result))
    with pytest.raises(WorkflowError):
        authorization(result, no_yield=ids)
    assert not fake.deletes


def test_no_yield_ids_cannot_cover_processed_and_legacy_authorization_cannot_expand(setup):
    start, fake, target, _material, _source = setup
    result = start()
    submit(result, review_for(result, target))
    with pytest.raises(WorkflowError, match="no_yield_ids"):
        authorization(result, no_yield=["1001"])
    approved = authorization(result)  # 旧格式对processed继续有效，原授权字节不重写。
    authorization_path = Path(result["job"]) / approved["authorization"]
    original = authorization_path.read_bytes()
    submit(result, no_yield_review(result))
    with pytest.raises(WorkflowError, match="no_yield_ids"):
        c.cleanup(result["job"], True)
    assert authorization_path.read_bytes() == original and not fake.deletes


def test_no_yield_still_protects_github_folder(setup):
    start, fake, _target, _material, _source = setup
    result = start()
    submit(result, no_yield_review(result))
    authorization(result, no_yield=["1001"])
    fake.folder_rows = [{"id": "github", "name": "GitHub", "parent_id": None}]
    fake.cards["1001"]["card"]["folder"] = {"id": "github", "name": "GitHub"}
    with pytest.raises(WorkflowError, match="保护"):
        c.cleanup(result["job"], True)
    assert not fake.deletes
