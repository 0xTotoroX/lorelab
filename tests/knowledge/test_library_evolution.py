"""真实文件上的分类反馈闭环：稳定身份、完整回读、幂等恢复和人工修改保护。"""

import json
from pathlib import Path

import pytest

from lorelab.knowledge import library
from lorelab.knowledge import library_allocation as allocation
from lorelab.knowledge import library_evolution as evolution
from lorelab.knowledge.workflow_state import WorkflowError, digest


def setup(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    root = vault / "Knowledge"
    library.init(root)
    (root / "旧目录").mkdir()
    (root / "旧目录/甲.md").write_text("# 甲\n工具与操作\n")
    (root / "旧目录/乙.md").write_text("# 乙\n饮食与生活\n")
    (root / evolution.INDEX).write_text("# 原导航\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    prepared = evolution.prepare(vault, "Knowledge", "名称简短，按实际内容", state_root=tmp_path / "jobs")
    review = {"rationale": "文章实际分为工具和生活，一层即可。", "categories": [
        {"key": "new:tools", "name": "工具", "parent": None, "scope": "工具操作", "evidence": ["旧目录/甲.md"]},
        {"key": "new:life", "name": "生活", "parent": None, "scope": "日常生活", "evidence": ["旧目录/乙.md"]}],
        "assignments": [{"path": "旧目录/甲.md", "category": "new:tools", "reason": "正文为操作方法"},
                        {"path": "旧目录/乙.md", "category": "new:life", "reason": "正文为生活方法"}], "unassigned": []}
    file = Path(prepared["job"]) / "review.json"
    file.write_text(json.dumps(review, ensure_ascii=False))
    return vault, root, prepared["job"], file, review


def write(file, review):
    file.write_text(json.dumps(review, ensure_ascii=False))


def test_default_starts_small_and_keeps_existing_user_taxonomy(tmp_path):
    library.init(tmp_path)
    taxonomy = library.load(tmp_path)
    assert taxonomy["categories"] == [] and taxonomy["schema_version"] == 2
    taxonomy["title"] = "My name"
    write(tmp_path / library.TAXONOMY_FILE, taxonomy)
    assert library.init(tmp_path)["created"] is False
    assert library.load(tmp_path)["title"] == "My name"


def test_apply_replay_and_rollback_preserve_originals(tmp_path, monkeypatch):
    _vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    before = evolution.controls(root)
    originals = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (root / "旧目录").iterdir()}
    preview = evolution.preview(job, file)
    assert preview["classified_after"] == 2 and preview["files_moved"] == 0
    assert evolution.controls(root) == before
    assert evolution.apply(job, file)["status"] == "applied"
    assert library.catalog(root, category="K0001")["articles"][0]["relative_path"] == "旧目录/甲.md"
    mtimes = {name: (root / name).stat().st_mtime_ns for name in evolution.CONTROLS}
    evolution.apply(job)
    assert all((root / name).stat().st_mtime_ns == value for name, value in mtimes.items())
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in originals.items())
    assert evolution.status(job)["controls_match"]
    assert evolution.rollback(job)["status"] == "rolled_back"
    assert evolution.controls(root) == before
    assert evolution.rollback(job)["status"] == "rolled_back"
    with pytest.raises(WorkflowError, match="撤回"):
        evolution.apply(job)


@pytest.mark.parametrize("change", ["article", "new_article", "taxonomy", "index", "symlink"])
def test_changes_after_observation_block_without_overwrite(tmp_path, monkeypatch, change):
    _vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    if change == "article":
        (root / "旧目录/甲.md").write_text("# 甲\nHuman edit")
    elif change == "new_article":
        (root / "新.md").write_text("# 新")
    elif change == "taxonomy":
        value = library.load(root)
        value["title"] = "Human taxonomy"
        write(root / library.TAXONOMY_FILE, value)
    elif change == "index":
        (root / evolution.INDEX).write_text("Human index")
    else:
        (root / evolution.INDEX).unlink()
        (root / evolution.INDEX).symlink_to(root / "旧目录/甲.md")
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(WorkflowError):
        evolution.apply(job, file)
    assert all(p.read_bytes() == data for p, data in before.items())


def test_interrupted_apply_recovers_without_reapplying_first_write(tmp_path, monkeypatch):
    _vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    original = evolution._write

    def fail_index(root, name, body):
        if name == evolution.INDEX:
            raise OSError("simulated interruption")
        return original(root, name, body)

    monkeypatch.setattr(evolution, "_write", fail_index)
    with pytest.raises(OSError):
        evolution.apply(job, file)
    mtime = (root / library.TAXONOMY_FILE).stat().st_mtime_ns
    monkeypatch.setattr(evolution, "_write", original)
    assert evolution.apply(job)["status"] == "applied"
    assert (root / library.TAXONOMY_FILE).stat().st_mtime_ns == mtime


@pytest.mark.parametrize("problem", ["cycle", "unknown_evidence", "duplicate_assignment", "unknown_category", "reserved_name"])
def test_invalid_review_rejected_before_writes(tmp_path, monkeypatch, problem):
    _vault, root, job, file, review = setup(tmp_path, monkeypatch)
    if problem == "cycle":
        review["categories"][0]["parent"] = "new:life"
        review["categories"][1]["parent"] = "new:tools"
    elif problem == "unknown_evidence":
        review["categories"][0]["evidence"] = ["invented"]
    elif problem == "duplicate_assignment":
        review["assignments"].append(review["assignments"][0])
    elif problem == "reserved_name":
        review["categories"][0]["name"] = "CON"
    else:
        review["assignments"][0]["category"] = "missing"
    write(file, review)
    before = evolution.controls(root)
    with pytest.raises(WorkflowError):
        evolution.apply(job, file)
    assert evolution.controls(root) == before


def test_reorder_and_rename_keep_codes_paths_and_original_assignments(tmp_path, monkeypatch):
    vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    evolution.apply(job, file)
    before = library.load(root)
    prepared = evolution.prepare(vault, "Knowledge", "生活放前面", state_root=tmp_path / "jobs")
    review_file = Path(prepared["review_template"])
    review = json.loads(review_file.read_text())
    review["rationale"] = "用户要求改变顺序和名称，保留身份及路径。"
    review["categories"].reverse()
    review["categories"][0]["name"] = "日常"
    write(review_file, review)
    evolution.apply(prepared["job"], review_file)
    after = library.load(root)
    assert after["assignments"] == before["assignments"]
    assert library.paths(after) == library.paths(before)
    assert "01 日常 [K0002]" in library.tree(after)
    assert evolution.status(prepared["job"])["articles_unchanged"]
    with pytest.raises(WorkflowError, match="后续修改"):
        evolution.rollback(job)


def test_noop_does_not_create_taxonomy_version(tmp_path, monkeypatch):
    vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    evolution.apply(job, file)
    before = evolution.controls(root)
    prepared = evolution.prepare(vault, "Knowledge", state_root=tmp_path / "jobs")
    review_file = Path(prepared["review_template"])
    review = json.loads(review_file.read_text())
    review["rationale"] = "本次复查未发现需要调整的分类。"
    write(review_file, review)
    evolution.apply(prepared["job"], review_file)
    assert evolution.controls(root) == before


def test_new_class_after_prepare_is_usable_but_retired_class_stops(tmp_path, monkeypatch):
    vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    frozen = library.load(root)
    evolution.apply(job, file)
    body = "# 新文章\n内容"
    note = {"title": "新文章", "category": "K0001", "relative_path": "工具/新文章.md",
            "markdown": body, "body_sha256": digest(body.encode())}
    spec = {"vault": str(vault), "subdir": "Knowledge", "destination": str(root), "library": frozen}
    library.check_notes(spec, [note])
    note["category"] = "K0099"
    with pytest.raises(WorkflowError, match="退役"):
        library.check_notes(spec, [note])


def test_retiring_category_requires_explicit_reassignment(tmp_path, monkeypatch):
    vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    evolution.apply(job, file)
    prepared = evolution.prepare(vault, "Knowledge", state_root=tmp_path / "jobs")
    review_file = Path(prepared["review_template"])
    review = json.loads(review_file.read_text())
    review["rationale"] = "合并两个类别。"
    review["categories"] = review["categories"][:1]
    write(review_file, review)
    with pytest.raises(WorkflowError, match="退役类别仍有文章"):
        evolution.apply(prepared["job"], review_file)
    review["assignments"] = [{"path": "旧目录/乙.md", "category": "K0001", "reason": "明确合并"}]
    write(review_file, review)
    evolution.apply(prepared["job"], review_file)
    assert "K0002" in library.load(root)["retired_codes"]


def test_new_source_context_is_frozen_as_evidence(tmp_path, monkeypatch):
    vault, _root, _job, _file, review = setup(tmp_path, monkeypatch)
    context = tmp_path / "new.txt"
    context.write_text("新来源涉及学习方法")
    prepared = evolution.prepare(vault, "Knowledge", context=context, state_root=tmp_path / "jobs")
    review["categories"].append({"key": "new:study", "name": "学习", "parent": None,
                                 "scope": "学习方法", "evidence": ["@context"]})
    context.write_text("外部文件已改变，冻结证据保留原文")
    file = Path(prepared["job"]) / "review.json"
    write(file, review)
    assert evolution.preview(prepared["job"], file)["categories_after"] == 3
    observed = json.loads(Path(prepared["observed"]).read_text())
    assert observed["context"] == "新来源涉及学习方法"


def test_rollback_never_reuses_ids_for_another_meaning(tmp_path, monkeypatch):
    vault, root, job, file, review = setup(tmp_path, monkeypatch)
    evolution.apply(job, file)
    frozen = library.load(root)
    ledger = (root / allocation.FILE).read_bytes()
    evolution.rollback(job)
    assert (root / allocation.FILE).read_bytes() == ledger
    prepared = evolution.prepare(vault, "Knowledge", "改变含义", state_root=tmp_path / "jobs")
    review["categories"][0]["scope"] = "同名目录但不同含义"
    new_file = Path(prepared["job"]) / "review.json"
    write(new_file, review)
    evolution.apply(prepared["job"], new_file)
    assert library.load(root)["categories"][0]["code"] == "K0003"
    body = "# 新文章\n内容"
    note = {"title": "新文章", "category": "K0001", "relative_path": "工具/新文章.md",
            "markdown": body, "body_sha256": digest(body.encode())}
    spec = {"vault": str(vault), "subdir": "Knowledge", "destination": str(root), "library": frozen}
    with pytest.raises(WorkflowError, match="退役"):
        library.check_notes(spec, [note])


def test_pending_previews_do_not_reuse_reserved_ids_after_rollback(tmp_path, monkeypatch):
    vault, root, job, file, review = setup(tmp_path, monkeypatch)
    pending = evolution.prepare(vault, "Knowledge", "另一个方案", state_root=tmp_path / "jobs")
    pending_file = Path(pending["job"]) / "review.json"
    write(pending_file, review)
    evolution.apply(job, file)
    evolution.rollback(job)
    before = evolution.controls(root)
    with pytest.raises(WorkflowError, match="编号已被"):
        evolution.apply(pending["job"], pending_file)
    assert evolution.controls(root) == before


def test_explicit_unassigned_overrides_directory_and_survives_next_review(tmp_path, monkeypatch):
    vault, root, job, file, _review = setup(tmp_path, monkeypatch)
    evolution.apply(job, file)
    (root / "工具").mkdir()
    (root / "工具/Topic.MD").write_text("# Topic\n不适合工具类别")
    for attempt in range(2):
        prepared = evolution.prepare(vault, "Knowledge", "暂时不分类", state_root=tmp_path / "jobs")
        next_file = Path(prepared["review_template"])
        review = json.loads(next_file.read_text())
        review["rationale"] = "正文需要待归类"
        if attempt == 0:
            review["unassigned"] = [{"path": "工具/Topic.MD", "reason": "与目录含义不符"}]
        write(next_file, review)
        assert evolution.apply(prepared["job"], next_file)["classified_after"] == 2
        assert library.load(root)["assignments"]["工具/Topic.MD"] is None
        assert library.catalog(root)["uncategorized"] == ["工具/Topic.MD"]
    body = (root / "工具/Topic.MD").read_text()
    note = {"title": "Topic", "category": "K0001", "relative_path": "工具/Topic.MD",
            "markdown": body, "body_sha256": digest(body.encode())}
    spec = {"vault": str(vault), "subdir": "Knowledge", "destination": str(root), "library": library.load(root)}
    with pytest.raises(WorkflowError, match="现有归属"):
        library.check_notes(spec, [note])


def test_bom_crlf_rollback_restores_bytes_and_custom_title(tmp_path, monkeypatch):
    vault, root, _job, file, _review = setup(tmp_path, monkeypatch)
    taxonomy = library.load(root)
    taxonomy["title"] = "我的知识库"
    raw = b'\xef\xbb\xbf' + (json.dumps(taxonomy, ensure_ascii=False, indent=2) + '\n').replace('\n', '\r\n').encode()
    (root / library.TAXONOMY_FILE).write_bytes(raw)
    (root / evolution.INDEX).write_bytes(b'\xef\xbb\xbf# My index\r\n\r\nHuman\r\n')
    before = {name: (root / name).read_bytes() for name in evolution.CONTROLS}
    prepared = evolution.prepare(vault, "Knowledge", state_root=tmp_path / "jobs")
    evolution.apply(prepared["job"], file)
    assert library.load(root)["title"] == "我的知识库"
    assert (root / evolution.INDEX).read_text().startswith("# 我的知识库\n")
    evolution.rollback(prepared["job"])
    assert {name: (root / name).read_bytes() for name in evolution.CONTROLS} == before
