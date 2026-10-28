"""图书馆分类保持单份正文，冻结分类，并保护旧文章及人工修改。"""

import json
from pathlib import Path

import pytest

from lorelab.knowledge import cli, library
from lorelab.knowledge import workflow as w
from lorelab.knowledge.workflow_state import WorkflowError

from .support import FakeCLI, card, review_for, write


def prepare_library(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    root = vault / "Knowledge"
    library.init(root, Path(library.__file__).with_name("world_taxonomy.json"))
    fake = FakeCLI([card("a")])
    monkeypatch.setattr(w, "run_json", fake)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    ids = tmp_path / "ids.txt"
    ids.write_text("a\n")
    result = w.prepare(ids, vault, "Knowledge", state_root=tmp_path / "jobs", delete_verified=True)
    review = review_for(result, vault)
    note = review["notes"][0]
    note["category"] = "06.04"
    note["related_categories"] = ["00.01"]
    note["relative_path"] = library.paths(result["library"]["taxonomy"])["06.04"] + "/" + note["title"] + ".md"
    path = Path(result["job"]) / "review.json"
    write(path, review)
    return fake, result, root, path, review


def test_init_repeat_preserves_tree_and_human_taxonomy(tmp_path):
    root = tmp_path / "Knowledge"
    result = library.init(root, Path(library.__file__).with_name("world_taxonomy.json"))
    path = root / library.TAXONOMY_FILE
    original, mtime = path.read_bytes(), path.stat().st_mtime_ns
    assert result["created"] and "06.04 人工智能与智能体" in result["tree"]
    assert library.init(root, Path(library.__file__).with_name("world_taxonomy.json"))["created"] is False
    assert path.read_bytes() == original and path.stat().st_mtime_ns == mtime
    assert list(root.iterdir()) == [path]  # 没有为了大纲预建空文件夹。
    value = json.loads(original)
    value["title"] = "Human library"
    write(path, value)
    with pytest.raises(WorkflowError, match="不覆盖"):
        library.init(root, Path(library.__file__).with_name("world_taxonomy.json"))
    assert library.load(root)["title"] == "Human library"


@pytest.mark.parametrize("change", ["duplicate", "parent", "traversal", "nonstring", "unicode"])
def test_invalid_taxonomy_rejected(tmp_path, change):
    library.init(tmp_path, Path(library.__file__).with_name("world_taxonomy.json"))
    value = library.load(tmp_path)
    if change == "duplicate":
        value["categories"].append(value["categories"][0])
    elif change == "parent":
        value["categories"].append({"code": "99.01", "name": "Orphan"})
    elif change == "traversal":
        value["categories"][0]["name"] = "../outside"
    elif change == "nonstring":
        value["categories"][0]["code"] = 0
    else:
        value["categories"][0]["code"] = "００"
    with pytest.raises(WorkflowError):
        library.validate(value)


def test_catalog_finds_existing_notes_without_modification_or_symlink_traversal(tmp_path):
    root = tmp_path / "Knowledge"
    library.init(root, Path(library.__file__).with_name("world_taxonomy.json"))
    old = root / "Old"
    old.mkdir()
    first = old / "Original.md"
    first.write_text("---\n# Metadata comment\n主题: example\n---\n# Real title\nneedle\n")
    second = old / "Different.md"
    second.write_text("# Real title\nOther text\n")
    (root / "AGENTS.md").write_text("# Rules")
    (root / "知识索引.md").write_text("# Index")
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.md").write_text("secret")
    (root / "outside").symlink_to(outside, target_is_directory=True)
    (root / "linked.md").symlink_to(outside / "secret.md")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in [first, second]}
    result = library.catalog(root)
    assert result["count"] == 2 and len(result["duplicate_titles"]) == 1
    assert result["skipped_symlinks"] == ["linked.md", "outside"]
    assert library.catalog(root, query="needle")["count"] == 1
    assert library.catalog(root, category="06")["count"] == 0
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == v for p, v in before.items())


def test_classified_publish_replay_and_human_edit_cleanup_guard(tmp_path, monkeypatch):
    fake, result, root, review_path, review = prepare_library(tmp_path, monkeypatch)
    snapshot = Path(result["library"]["catalog_snapshot"])
    assert json.loads(snapshot.read_text())["count"] == 0
    w.submit(result["job"], review_path)
    assert w.publish(result["job"])["status"] == "verified"
    article = root / review["notes"][0]["relative_path"]
    before = (article.read_bytes(), article.stat().st_mtime_ns)
    assert w.publish(result["job"])["status"] == "verified"
    assert before == (article.read_bytes(), article.stat().st_mtime_ns)
    assert library.catalog(root, category="06")["count"] == 1
    assert w.verify(result["job"])["status"] == "verified"
    article.write_text(article.read_text() + "\nHuman addition\n")
    with pytest.raises(WorkflowError, match="已修改"):
        w.cleanup(result["job"], True)
    assert fake.deletes == 0 and fake.imports == 0


@pytest.mark.parametrize("when", ["submit", "publish"])
@pytest.mark.parametrize("heading", ["# Topic a", "# Topic a #", "Topic a\n===", "```md\n# Code\n```\n# Topic a"])
def test_existing_title_elsewhere_blocks_new_copy(tmp_path, monkeypatch, when, heading):
    _fake, result, root, review_path, _review = prepare_library(tmp_path, monkeypatch)
    if when == "publish":
        w.submit(result["job"], review_path)
    old = root / "Old"
    old.mkdir()
    content = heading + "\nHuman content\n"
    (old / "Keep.md").write_text(content)
    with pytest.raises(WorkflowError, match="已存在同标题"):
        if when == "submit":
            w.submit(result["job"], review_path)
        else:
            w.publish(result["job"])
    assert (old / "Keep.md").read_text() == content
    assert len(list(root.rglob("*.md"))) == 1


def test_identical_bodies_in_same_batch_stop_before_any_write(tmp_path, monkeypatch):
    fake, result, root, review_path, review = prepare_library(tmp_path, monkeypatch)
    from copy import deepcopy

    from .support import sha

    first = review["notes"][0]
    first["markdown"] = first["markdown"].split("\n", 1)[1]
    first["body_sha256"] = sha(first["markdown"])
    second = deepcopy(first)
    second["title"] = "Another title"
    second["relative_path"] = str(Path(second["relative_path"]).with_name("Another title.md"))
    review["notes"].append(second)
    write(review_path, review)
    before = len(fake.calls)
    with pytest.raises(WorkflowError, match="同批文章正文重复"):
        w.submit(result["job"], review_path)
    assert len(fake.calls) == before and not list(root.rglob("*.md"))


@pytest.mark.parametrize("change", ["code", "path", "related", "taxonomy", "navigation"])
def test_invalid_or_changed_classification_blocks_submission(tmp_path, monkeypatch, change):
    fake, result, root, review_path, review = prepare_library(tmp_path, monkeypatch)
    if change == "code":
        review["notes"][0]["category"] = "99"
    elif change == "path":
        review["notes"][0]["relative_path"] = "Topic a.md"
    elif change == "related":
        review["notes"][0]["related_categories"] = ["99"]
    elif change == "navigation":
        note = review["notes"][0]
        note["title"] = "知识索引"
        note["relative_path"] = str(Path(note["relative_path"]).with_name("知识索引.md"))
    else:
        taxonomy = library.load(root)
        taxonomy["version"] += 1
        write(root / library.TAXONOMY_FILE, taxonomy)
    write(review_path, review)
    before = len(fake.calls)
    with pytest.raises(WorkflowError):
        w.submit(result["job"], review_path)
    assert len(fake.calls) == before
    assert not list(root.rglob("*.md"))


def test_library_cli_uses_config_without_altering_it(tmp_path, monkeypatch):
    config = {"vault": str(tmp_path), "subdir": "Knowledge", "delete_verified": True}
    monkeypatch.setattr(cli.runtime, "read_config", lambda: dict(config))
    result = cli.dispatch(cli.parser().parse_args(["knowledge", "library", "init"]))
    assert result["ok"]
    result = cli.dispatch(cli.parser().parse_args(["knowledge", "library", "tree"]))
    assert result["paths"] == {} and result["taxonomy"]["schema_version"] == 2
    result = cli.dispatch(cli.parser().parse_args(["knowledge", "library", "catalog", "--query", "AI"]))
    assert result["count"] == 0
    assert cli.runtime.read_config() == config


def test_init_rejects_symlink_destination(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Knowledge").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(cli.runtime, "read_config", dict)
    args = cli.parser().parse_args(["knowledge", "library", "init", "--vault", str(vault), "--subdir", "Knowledge"])
    with pytest.raises(WorkflowError, match="符号链接"):
        cli.dispatch(args)
    assert not list(outside.iterdir())
