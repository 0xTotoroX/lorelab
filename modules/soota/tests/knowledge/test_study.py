"""显式文章学习的快照、保全与幕布恢复；全部服务调用使用 fake Mubu。"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from soota.knowledge import study
from soota.knowledge import workflow_publish as publisher
from soota.knowledge.workflow_state import WorkflowError, lock

from .support import FakeCLI, sha, write


class FakeMubu(FakeCLI):
    def __init__(self):
        super().__init__([])

    def __call__(self, tool, args, **kwargs):
        assert tool == "mubu", "study must never fetch sources or depend on Cubox/Soota"
        return super().__call__(tool, args, **kwargs)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    vault = root / "vault"
    vault.mkdir()
    (vault / "nested").mkdir()
    article = vault / "nested/article.md"
    article.write_bytes("\ufeff# Learning title\r\n\r\nExact original body.\r\n".encode("utf-8"))
    (vault / "unrelated.md").write_bytes(b"# Unrelated\n\nHuman content.\n")
    (vault / "AGENTS.md").write_bytes(b"Personal instructions stay here.\n")
    fake = FakeMubu()
    monkeypatch.setattr(study, "run_json", fake)
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "global"))
    monkeypatch.setenv("LOREHUB_STATE_DIR", str(root / "jobs"))
    return vault, article, fake


@pytest.fixture
def shared_publisher(monkeypatch):
    """直接覆盖真实共享发布器，并确保学习任务完全不调用文章写入。"""
    monkeypatch.setattr(study, "publish_approved", publisher.publish_approved)
    monkeypatch.setattr(study, "reconcile", publisher.reconcile)

    def forbidden(*args, **kwargs):
        pytest.fail("study must not call write_notes, even for an identical existing article")

    monkeypatch.setattr(publisher, "write_notes", forbidden)


def start(workspace, **kwargs):
    vault, article, _fake = workspace
    return study.prepare([article], vault, "doc", **kwargs)


def review_for(result):
    review = json.loads(Path(result["review_template"]).read_bytes())
    for entry in review["articles"]:
        entry["review_notes"] = (
            "Read the exact article: its conditions limit the claim; retain those limits for review."
        )
        entry["outline"]["children"] = [
            {
                "text": "Claim and scope",
                "note": "Keep the limiting condition.",
                "children": [{"text": "When it applies"}],
            }
        ]
    return review


def approve(result):
    path = Path(result["job"]) / "review.json"
    review = review_for(result)
    write(path, review)
    return study.submit(result["job"], path), path, review


def vault_snapshot(vault):
    return {
        p.relative_to(vault).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in vault.rglob("*") if p.is_file()
    }


def reseal(job, name, value):
    """模拟同时改写状态中的校验和，确保跨产物身份检查也能捕获不一致。"""
    folder = Path(job)
    write(folder / name, value)
    state = json.loads((folder / "job.json").read_bytes())
    state["sealed"][name] = sha((folder / name).read_bytes())
    write(folder / "job.json", state)


def test_prepare_is_offline_exact_private_and_explicit(workspace):
    vault, article, fake = workspace
    before = vault_snapshot(vault)
    result = start(workspace)
    folder = Path(result["job"])
    assert result["kind"] == "study" and result["status"] == "waiting_review"
    assert not fake.calls and result["notes"] == {"nested/article.md": sha(article.read_bytes())}
    spec = json.loads((folder / "spec.json").read_bytes())
    assert spec == {
        "kind": "study",
        "with_outline": True,
        "vault": str(vault),
        "subdir": "",
        "destination": str(vault),
        "mubu_doc": "doc",
        "mubu_parent": None,
        "mubu_auth": "desktop",
    }
    snapshots = json.loads(Path(result["article_snapshot"]).read_bytes())
    assert len(snapshots) == 1 and snapshots[0]["markdown"].encode("utf-8") == article.read_bytes()
    assert result["articles"] == [
        {
            "relative_path": "nested/article.md",
            "title": "Learning title",
            "body_sha256": sha(article.read_bytes()),
        }
    ]
    assert json.loads(Path(result["review_template"]).read_bytes()) == {
        "articles": [
            {
                "relative_path": "nested/article.md",
                "body_sha256": sha(article.read_bytes()),
                "review_notes": "",
                "outline": {"text": "Learning title", "children": []},
            }
        ]
    }
    assert not folder.is_relative_to(vault)
    assert folder.stat().st_mode & 0o777 == 0o700
    for name in ("spec.json", "articles.json", "job.json", "review-template.json"):
        assert (folder / name).stat().st_mode & 0o777 == 0o600
    assert study.status(result["job"])["status"] == "waiting_review"
    assert not fake.calls and vault_snapshot(vault) == before


@pytest.mark.parametrize(
    ("body", "title"),
    [
        ("# Actual H1 ###\nBody\n", "Actual H1"),
        ("---\ntitle: Metadata\n---\n```md\n# Example\n```\n# Actual title\n", "Actual title"),
        ("~~~markdown\n# Example\n~~~~\n# Actual title\n", "Actual title"),
        ("Setext title\n===\nBody", "Setext title"),
        ("---\n# Actual title\nBody", "Actual title"),
        ("# ###\nBody", "article"),
        ("## Section only\nBody\n", "article"),
    ],
)
def test_real_h1_or_filename_fallback(workspace, body, title):
    _vault, article, _fake = workspace
    article.write_text(body, encoding="utf-8")
    result = start(workspace)
    assert result["articles"][0]["title"] == title
    assert json.loads(Path(result["review_template"]).read_bytes())["articles"][0]["outline"]["text"] == title


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.md",
        "nested/../../outside.md",
        "nested\\article.md",
        "C:article.md",
        "bad\nname.md",
        ".hidden.md",
        ".obsidian/article.md",
        "nested/.hidden/article.md",
        "AGENTS.md",
        "claude.MD",
        "AGENTS.override.md",
        "GEMINI.md",
        "SKILL.md",
        "notes.txt",
        "missing.md",
    ],
)
def test_unsafe_or_missing_selection_rejected_before_job(workspace, relative):
    vault, _article, fake = workspace
    path = vault / relative
    if ".." not in Path(relative).parts and relative != "missing.md":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic\nText", encoding="utf-8")
    with pytest.raises(WorkflowError):
        study.prepare([Path(relative)], vault, "doc")
    assert not fake.calls and not (vault.parent / "jobs").exists()


def test_absolute_escape_and_symlinks_are_not_resolved_away(workspace):
    vault, article, fake = workspace
    outside = vault.parent / "outside.md"
    outside.write_text("# Outside\nText", encoding="utf-8")
    link = vault / "link.md"
    link.symlink_to(article)
    directory = vault / "alias"
    directory.symlink_to(article.parent, target_is_directory=True)
    alias = vault.parent / "vault-link"
    alias.symlink_to(vault, target_is_directory=True)
    for path, selected_vault in [(outside, vault), (link, vault), (directory / article.name, vault), (article, alias)]:
        with pytest.raises(WorkflowError):
            study.prepare([path], selected_vault, "doc")
    assert not fake.calls


@pytest.mark.parametrize("root_kind", ["inside", "same", "ancestor", "symlink-inside"])
def test_state_root_must_be_separate(workspace, root_kind):
    vault, _article, fake = workspace
    root = {"inside": vault / "private", "same": vault, "ancestor": vault.parent}.get(root_kind)
    if root_kind == "symlink-inside":
        root = vault.parent / "alias"
        root.symlink_to(vault, target_is_directory=True)
    with pytest.raises(WorkflowError, match="分离"):
        start(workspace, state_root=root)
    assert not fake.calls


@pytest.mark.parametrize("invalid", [b"", b" \n\t", b"\xff\xfe"])
def test_empty_or_non_utf8_article_rejected(workspace, invalid):
    _vault, article, fake = workspace
    article.write_bytes(invalid)
    with pytest.raises(WorkflowError):
        start(workspace)
    assert not fake.calls


@pytest.mark.parametrize("case", ["identical", "path-casefold", "title-casefold", "title-nfc"])
def test_duplicate_paths_or_titles_rejected(workspace, case):
    vault, article, fake = workspace
    other = vault / "other.md"
    other.write_text("# Other title\nText", encoding="utf-8")
    if case == "identical":
        other = article
    elif case == "path-casefold":
        # 即使文件系统区分大小写，也不能向跨平台 job 引入同一路径身份。
        other = vault / "nested/ARTICLE.md"
        other.write_bytes(article.read_bytes())
    elif case == "title-casefold":
        other.write_text("# learning TITLE\nOther body", encoding="utf-8")
    else:
        article.write_text("# Caf\u00e9\nBody", encoding="utf-8")
        other.write_text("# Cafe\u0301\nOther body", encoding="utf-8")
    with pytest.raises(WorkflowError, match="重复"):
        study.prepare([article, other], vault, "doc")
    assert not fake.calls


def test_relative_selection_and_all_articles_once_in_original_order(workspace):
    vault, article, fake = workspace
    other = vault / "other.md"
    other.write_text("# Another topic\nSecond article", encoding="utf-8")
    result = study.prepare([article.relative_to(vault), Path("other.md")], vault, "doc")
    review = review_for(result)
    review["articles"].reverse()
    draft = Path(result["job"]) / "review.json"
    write(draft, review)
    approved = study.submit(result["job"], draft)
    frozen = json.loads((Path(result["job"]) / "approved.json").read_bytes())
    assert [a["relative_path"] for a in frozen["articles"]] == ["nested/article.md", "other.md"]
    assert [n["title"] for n in frozen["notes"]] == ["Learning title", "Another topic"]
    assert approved["notes"] == {"nested/article.md": sha(article.read_bytes()), "other.md": sha(other.read_bytes())}
    assert not fake.calls


def test_duplicate_review_identity_cannot_replace_another_selected_article(workspace):
    vault, article, fake = workspace
    result = study.prepare([article, vault / "unrelated.md"], vault, "doc")
    review = review_for(result)
    review["articles"][1] = deepcopy(review["articles"][0])
    draft = Path(result["job"]) / "review.json"
    write(draft, review)
    with pytest.raises(WorkflowError, match="身份"):
        study.submit(result["job"], draft)
    assert not fake.calls


@pytest.mark.parametrize(
    "mutation",
    [
        "omitted",
        "duplicate",
        "wrong-path",
        "path-casefold",
        "wrong-hash",
        "extra-field",
        "wrong-top",
        "renamed-root",
        "bad-node",
        "bad-note",
        "too-many-nodes",
        "too-deep",
        "too-large",
    ],
)
def test_review_identity_and_outline_validation(workspace, mutation):
    vault, _article, fake = workspace
    before = vault_snapshot(vault)
    result = start(workspace)
    review = review_for(result)
    entry = review["articles"][0]
    if mutation == "omitted":
        review["articles"] = []
    elif mutation == "duplicate":
        review["articles"].append(deepcopy(entry))
    elif mutation == "wrong-path":
        entry["relative_path"] = "unrelated.md"
    elif mutation == "path-casefold":
        entry["relative_path"] = "nested/ARTICLE.md"
    elif mutation == "wrong-hash":
        entry["body_sha256"] = "0" * 64
    elif mutation == "extra-field":
        entry["markdown"] = "# Replacement"
    elif mutation == "wrong-top":
        review["sources"] = []
    elif mutation == "renamed-root":
        entry["outline"]["text"] = "Filename instead of the original caption"
    elif mutation == "bad-node":
        entry["outline"]["children"] = [{"text": "Point", "unrecognized": True}]
    elif mutation == "bad-note":
        entry["outline"]["note"] = ["not text"]
    elif mutation == "too-many-nodes":
        entry["outline"]["children"] = [{"text": str(i)} for i in range(500)]
    elif mutation == "too-deep":
        node = entry["outline"]
        for _ in range(33):
            node["children"] = [{"text": "Nested"}]
            node = node["children"][0]
    else:
        entry["outline"]["note"] = "x" * (512 * 1024)
    path = Path(result["job"]) / "review.json"
    write(path, review)
    with pytest.raises(WorkflowError):
        study.submit(result["job"], path)
    assert not (Path(result["job"]) / "approved.json").exists()
    assert not fake.calls and vault_snapshot(vault) == before


@pytest.mark.parametrize("notes", [None, "", " \n ", "TODO", "ok", "已审阅", "...", "✅"])
def test_review_requires_concrete_notes(workspace, notes):
    result = start(workspace)
    review = review_for(result)
    review["articles"][0]["review_notes"] = notes
    path = Path(result["job"]) / "review.json"
    write(path, review)
    with pytest.raises(WorkflowError, match="review_notes"):
        study.submit(result["job"], path)


def test_approved_freezes_exact_article_and_agent_outline(workspace):
    vault, article, fake = workspace
    before = vault_snapshot(vault)
    result = start(workspace)
    submitted, path, review = approve(result)
    folder = Path(result["job"])
    approved = json.loads((folder / "approved.json").read_bytes())
    assert submitted["status"] == "approved"
    assert approved == {
        "articles": review["articles"],
        "notes": [
            {
                "relative_path": "nested/article.md",
                "title": "Learning title",
                "markdown": article.read_bytes().decode(),
                "body_sha256": sha(article.read_bytes()),
                "outline": review["articles"][0]["outline"],
            }
        ],
    }
    assert json.loads((folder / "outline.json").read_bytes()) == {"nodes": [review["articles"][0]["outline"]]}
    assert study.submit(result["job"], path)["status"] == "approved"
    review["articles"][0]["review_notes"] += " Changed after approval."
    write(path, review)
    with pytest.raises(WorkflowError, match="冻结"):
        study.submit(result["job"], path)
    assert study.status(result["job"])["status"] == "approved"
    assert not fake.calls and vault_snapshot(vault) == before


@pytest.mark.parametrize("action", ["submit", "status", "publish", "verify"])
@pytest.mark.parametrize("change", ["modified", "missing", "symlink", "parent-symlink"])
def test_all_calls_require_current_unchanged_article(workspace, action, change):
    vault, article, fake = workspace
    result = start(workspace)
    _approved, draft, _review = approve(result)
    original = article.read_bytes()
    if change == "modified":
        article.write_bytes(original + b"Human edit\n")
    elif change == "missing":
        article.unlink()
    elif change == "symlink":
        copy = vault.parent / "copy.md"
        copy.write_bytes(original)
        article.unlink()
        article.symlink_to(copy)
    else:
        moved = vault.parent / "moved"
        article.parent.rename(moved)
        article.parent.symlink_to(moved, target_is_directory=True)
    with pytest.raises(WorkflowError):
        getattr(study, action)(result["job"], *([draft] if action == "submit" else []))
    assert not fake.calls
    if change == "missing":
        assert not article.exists()
    elif change == "modified":
        assert article.read_bytes() == original + b"Human edit\n"


def test_status_before_review_also_hash_checks(workspace):
    _vault, article, fake = workspace
    result = start(workspace)
    article.write_text("Human edit before review", encoding="utf-8")
    with pytest.raises(WorkflowError, match="修改"):
        study.status(result["job"])
    assert not fake.calls


@pytest.mark.parametrize("action", ["submit", "status", "publish", "verify"])
@pytest.mark.parametrize("location", ["state", "spec"])
def test_non_study_kind_rejected_by_every_entrypoint(workspace, action, location):
    _vault, _article, fake = workspace
    result = start(workspace)
    _approved, path, _review = approve(result)
    folder = Path(result["job"])
    name = "job.json" if location == "state" else "spec.json"
    value = json.loads((folder / name).read_bytes())
    value["kind"] = "batch"
    if location == "spec":
        reseal(result["job"], name, value)
    else:
        write(folder / name, value)
    with pytest.raises(WorkflowError, match="kind"):
        getattr(study, action)(result["job"], *([path] if action == "submit" else []))
    assert not fake.calls


@pytest.mark.parametrize("name", ["spec.json", "articles.json", "approved.json", "outline.json"])
def test_frozen_artifact_tampering_is_rejected(workspace, name):
    _vault, _article, fake = workspace
    result = start(workspace)
    approve(result)
    (Path(result["job"]) / name).write_text("{}", encoding="utf-8")
    with pytest.raises(WorkflowError, match="修改"):
        study.status(result["job"])
    assert not fake.calls


@pytest.mark.parametrize(
    "target", ["snapshot-hash", "snapshot-title", "snapshot-path", "approved-body", "outline", "notes-map"]
)
def test_cross_artifact_binding_detects_resealed_inconsistency(workspace, target):
    _vault, _article, fake = workspace
    result = start(workspace)
    approve(result)
    folder = Path(result["job"])
    name = {
        "snapshot-hash": "articles.json",
        "snapshot-title": "articles.json",
        "snapshot-path": "articles.json",
        "approved-body": "approved.json",
        "outline": "outline.json",
        "notes-map": "job.json",
    }[target]
    value = json.loads((folder / name).read_bytes())
    if target == "snapshot-hash":
        value[0]["markdown"] += "Changed"
    elif target == "snapshot-title":
        value[0]["title"] = "Different caption"
    elif target == "snapshot-path":
        value[0]["relative_path"] = None
    elif target == "approved-body":
        value["notes"][0]["markdown"] += "Changed"
    elif target == "outline":
        value["nodes"][0]["children"] = []
    else:
        value["notes"] = {}
    if name == "job.json":
        write(folder / name, value)
    else:
        reseal(result["job"], name, value)
    with pytest.raises(WorkflowError):
        study.status(result["job"])
    assert not fake.calls


def test_shared_calls_use_checker_read_only_articles_and_document_lock(workspace, monkeypatch):
    result = start(workspace)
    approve(result)
    calls = []

    def publish(run, job, state, *, checker, write_articles):
        assert run is study.run_json and checker is study.check_study and write_articles is False
        assert checker(job, state)["notes"][0]["title"] == "Learning title"
        calls.append("publish")

    def reconcile(run, job, state, approved, *, checker):
        assert run is study.run_json and checker is study.check_study
        assert approved == checker(job, state)
        spec = json.loads((job / "spec.json").read_bytes())
        with pytest.raises(WorkflowError, match="写入者"), publisher.writer(spec):
            pass
        calls.append("verify")
        return True

    monkeypatch.setattr(study, "publish_approved", publish)
    monkeypatch.setattr(study, "reconcile", reconcile)
    study.publish(result["job"])
    study.verify(result["job"])
    assert calls == ["publish", "verify"]


@pytest.mark.parametrize("parent", [None, "old-root"])
def test_full_study_and_repeated_recovery_preserve_articles_and_root_captions(workspace, shared_publisher, parent):
    vault, _article, fake = workspace
    before = vault_snapshot(vault)
    old_root = deepcopy(fake.nodes[0])
    result = start(workspace, mubu_parent=parent, mubu_auth="password")
    _approved, draft, _review = approve(result)
    write(draft, {"changed": "Mutable draft is no longer consulted"})
    assert fake.cards == {}  # 原收藏不再存在；学习仍只依赖已保存的文章。
    assert study.publish(result["job"])["status"] == "verified"
    assert study.publish(result["job"])["status"] == "verified"
    assert study.verify(result["job"])["status"] == "verified"
    assert fake.imports == 1 and all(tool == "mubu" for tool, _args, _codes in fake.calls)
    assert all(args[2] == "password" for _tool, args, _codes in fake.calls)
    assert fake.nodes[0]["text"] == old_root["text"] and fake.nodes[0]["note"] == old_root["note"]
    added = fake.nodes[-1] if parent is None else fake.nodes[0]["children"][0]
    assert added["text"] == "Learning title" and added["children"][0]["text"] == "Claim and scope"
    assert vault_snapshot(vault) == before
    count = len(fake.calls)
    assert study.status(result["job"])["status"] == "verified"
    assert len(fake.calls) == count


@pytest.mark.parametrize("mode", ["uncertain", "receipt_timeout", "operation_only", "timeout"])
def test_uncertain_import_recovers_without_reimport(workspace, shared_publisher, mode):
    vault, _article, fake = workspace
    before = vault_snapshot(vault)
    result = start(workspace)
    approve(result)
    fake.mode = mode
    if "timeout" in mode:
        with pytest.raises(RuntimeError, match="timeout"):
            study.publish(result["job"])
    else:
        study.publish(result["job"])
    outcome = study.publish(result["job"])
    assert fake.imports == 1
    assert outcome["status"] == ("publish_uncertain" if mode == "timeout" else "verified")
    if mode == "timeout":
        assert outcome["ok"] is False
        with pytest.raises(WorkflowError, match="不能重导入"):
            study.verify(result["job"])
    else:
        assert study.verify(result["job"])["status"] == "verified"
    assert fake.imports == 1 and vault_snapshot(vault) == before


def test_interrupted_before_dispatch_does_not_replay(workspace, shared_publisher, monkeypatch):
    _vault, _article, fake = workspace
    result = start(workspace)
    approve(result)

    def interrupted(tool, args, **kwargs):
        if "--execute" in args:
            raise KeyboardInterrupt()
        return fake(tool, args, **kwargs)

    monkeypatch.setattr(study, "run_json", interrupted)
    with pytest.raises(KeyboardInterrupt):
        study.publish(result["job"])
    monkeypatch.setattr(study, "run_json", fake)
    assert study.publish(result["job"])["status"] == "publish_uncertain"
    assert fake.imports == 0


def test_article_removed_during_preview_is_never_recreated(workspace, shared_publisher, monkeypatch):
    _vault, article, fake = workspace
    result = start(workspace)
    approve(result)

    def remove_during_preview(tool, args, **kwargs):
        response = fake(tool, args, **kwargs)
        if "node-import" in args and "--execute" not in args:
            article.unlink()
        return response

    monkeypatch.setattr(study, "run_json", remove_during_preview)
    with pytest.raises(WorkflowError, match="缺失"):
        study.publish(result["job"])
    assert not article.exists() and fake.imports == 0
    assert "mubu" not in json.loads((Path(result["job"]) / "job.json").read_bytes())


@pytest.mark.parametrize("phase", ["before-import", "after-import", "verify"])
@pytest.mark.parametrize("mutation", ["article", "outline"])
def test_cloud_reads_recheck_current_article_and_frozen_outline(
    workspace, shared_publisher, monkeypatch, phase, mutation
):
    _vault, article, fake = workspace
    result = start(workspace)
    approve(result)
    if phase == "verify":
        study.publish(result["job"])
    reads = 0
    target_read = 2 if phase == "after-import" else 1
    target = article if mutation == "article" else Path(result["job"]) / "outline.json"

    def change_during_read(tool, args, **kwargs):
        nonlocal reads
        response = fake(tool, args, **kwargs)
        if args[3] == "nodes":
            reads += 1
            if reads == target_read:
                target.write_bytes(target.read_bytes() + b"\nHuman change during cloud read\n")
        return response

    monkeypatch.setattr(study, "run_json", change_during_read)
    action = study.verify if phase == "verify" else study.publish
    with pytest.raises(WorkflowError, match="修改"):
        action(result["job"])
    expected_imports = 0 if phase == "before-import" else 1
    assert reads == target_read and fake.imports == expected_imports
    assert target.read_bytes().endswith(b"Human change during cloud read\n")
    with pytest.raises(WorkflowError):
        study.publish(result["job"])
    assert fake.imports == expected_imports


def test_uncertain_reconcile_early_return_still_rechecks_after_cloud_read(workspace, shared_publisher, monkeypatch):
    _vault, article, fake = workspace
    result = start(workspace)
    approve(result)
    fake.mode = "timeout"
    with pytest.raises(RuntimeError, match="timeout"):
        study.publish(result["job"])

    def changed_during_recovery(tool, args, **kwargs):
        response = fake(tool, args, **kwargs)
        if args[3] == "nodes":
            article.write_bytes(article.read_bytes() + b"Human edit during uncertain recovery\n")
        return response

    monkeypatch.setattr(study, "run_json", changed_during_recovery)
    with pytest.raises(WorkflowError, match="修改"):
        study.publish(result["job"])
    assert fake.imports == 1


def test_casefold_duplicate_cloud_root_blocks_import(workspace, shared_publisher):
    vault, _article, fake = workspace
    before = vault_snapshot(vault)
    fake.nodes[0]["text"] = "learning TITLE"
    result = start(workspace)
    approve(result)
    with pytest.raises(WorkflowError, match="同名主题"):
        study.publish(result["job"])
    assert fake.imports == 0 and vault_snapshot(vault) == before


@pytest.mark.parametrize("mutation", ["old-caption", "new-descendant"])
def test_verify_checks_whole_tree_and_never_repairs_it(workspace, shared_publisher, mutation):
    _vault, _article, fake = workspace
    result = start(workspace)
    approve(result)
    study.publish(result["job"])
    if mutation == "old-caption":
        fake.nodes[0]["text"] = "Human renamed root"
    else:
        fake.nodes[-1]["children"][0]["children"] = []
    before = deepcopy(fake.nodes)
    with pytest.raises(WorkflowError):
        study.verify(result["job"])
    assert fake.imports == 1 and fake.nodes == before


def test_verify_without_publish_does_not_import(workspace, shared_publisher):
    _vault, _article, fake = workspace
    result = start(workspace)
    approve(result)
    with pytest.raises(WorkflowError, match="不能重导入"):
        study.verify(result["job"])
    assert not fake.calls


def test_job_lock_is_shared_by_public_calls(workspace):
    result = start(workspace)
    _approved, path, _review = approve(result)
    with lock(Path(result["job"]) / ".lock"):
        for action in (study.status, study.publish, study.verify):
            with pytest.raises(WorkflowError, match="写入者"):
                action(result["job"])
        with pytest.raises(WorkflowError, match="写入者"):
            study.submit(result["job"], path)
