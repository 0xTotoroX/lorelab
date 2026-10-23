"""文章可独立交付；幕布故障不阻挡提炼，旧授权不会被升级放宽。"""

import json
from pathlib import Path

import pytest

from lorelab.knowledge import cli, runtime
from lorelab.knowledge import workflow as w
from lorelab.knowledge.workflow_state import WorkflowError

from .support import FakeCLI, card, review_for, sha, write


def start(tmp_path, monkeypatch, **options):
    vault = tmp_path / "vault"
    vault.mkdir()
    ids = tmp_path / "ids.txt"
    ids.write_text("a\nb\nmissing\ngithub")
    fake = FakeCLI(
        [
            card("a"),
            card("b"),
            card("missing", status="description_only"),
            card("github", url="https://github.com/example/tool"),
        ]
    )

    def invoke(tool, args, **kwargs):
        assert tool != "mubu", "文章批次不得读取、预览或写入幕布"
        return fake(tool, args, **kwargs)

    monkeypatch.setattr(w, "run_json", invoke)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    result = w.prepare(ids, vault, "Knowledge", state_root=tmp_path / "jobs", **options)
    review = review_for(result, vault)
    first, second = review["notes"]
    first["source_ids"].extend(second["source_ids"])
    first["markdown"] += "\n" + second["markdown"]
    first["body_sha256"] = sha(first["markdown"])
    review["notes"] = [first]
    path = Path(result["job"]) / "review.json"
    write(path, review)
    return fake, result, vault, path


def test_multiple_sources_form_one_article_without_mubu_then_cleanup(tmp_path, monkeypatch):
    fake, result, vault, review = start(tmp_path, monkeypatch, delete_verified=True)
    assert result["delivery"] == "article"
    template = json.loads(Path(result["review_template"]).read_text())
    assert "outline_markdown" not in template["sources"][0]["submission"]
    w.submit(result["job"], review)
    assert w.publish(result["job"])["article"]["status"] == "verified"
    assert w.verify(result["job"])["status"] == "verified"
    assert w.status(result["job"])["status"] == "verified"
    assert len(list(vault.rglob("*.md"))) == 1
    assert not list(Path(result["job"]).rglob("outline.*"))
    assert w.cleanup(result["job"])["cleanup_preview"]["eligible_ids"] == ["a", "b"]
    cleaned = w.cleanup(result["job"], True)
    assert cleaned["status"] == "cleaned"
    assert cleaned["retained_ids"] == ["missing", "github"]
    assert w.cleanup(result["job"], True)["status"] == "cleaned"
    assert w.publish(result["job"])["status"] == "cleaned"
    assert fake.deletes == 1 and fake.imports == 0


def test_old_outline_authorization_does_not_delete_article_only(tmp_path, monkeypatch):
    fake, result, _vault, review = start(tmp_path, monkeypatch, delete_verified=True, cleanup_after="outline")
    w.submit(result["job"], review)
    w.publish(result["job"])
    preview = w.cleanup(result["job"], True)["cleanup_preview"]
    assert preview["eligible_ids"] == [] and "原授权" in preview["reason"]
    assert fake.deletes == 0


def test_article_human_edit_blocks_cleanup(tmp_path, monkeypatch):
    fake, result, vault, review = start(tmp_path, monkeypatch, delete_verified=True)
    w.submit(result["job"], review)
    w.publish(result["job"])
    next(vault.rglob("*.md")).write_text("human changed this article")
    with pytest.raises(WorkflowError, match="文件已修改"):
        w.cleanup(result["job"], True)
    assert fake.deletes == 0


def test_article_cannot_accept_accidental_outline(tmp_path, monkeypatch):
    fake, result, _vault, review = start(tmp_path, monkeypatch)
    data = json.loads(review.read_text())
    data["notes"][0]["outline"] = {"text": "Unexpected extra delivery"}
    write(review, data)
    with pytest.raises(WorkflowError, match="笔记字段"):
        w.submit(result["job"], review)
    assert fake.imports == 0


def test_cli_old_config_keeps_cleanup_boundary_and_does_not_enable_mubu(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "read_config",
        lambda: {
            "vault": str(tmp_path),
            "subdir": "Knowledge",
            "mubu_doc": "existing-doc",
            "delete_verified": True,
        },
    )
    calls = []
    monkeypatch.setattr(w, "prepare", lambda *args, **kwargs: calls.append(kwargs))
    cli.dispatch(cli.parser().parse_args(["knowledge", "prepare", "--ids-file", str(tmp_path / "ids")]))
    assert calls[0]["with_outline"] is False
    assert calls[0]["cleanup_after"] == "outline"
    cli.dispatch(
        cli.parser().parse_args(
            ["knowledge", "prepare", "--ids-file", str(tmp_path / "ids"), "--cleanup-after", "article"]
        )
    )
    assert calls[1]["cleanup_after"] == "article"


def test_cli_article_init_needs_no_mubu(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    args = cli.parser().parse_args(["knowledge", "init", "--vault", str(tmp_path), "--subdir", "Knowledge"])
    result = cli.dispatch(args)
    assert result["settings"]["mubu_doc"] is None
    assert result["settings"]["cleanup_after"] == "article"
    assert result["settings"]["delete_verified"] is False


def test_cli_without_legacy_config_defaults_to_article_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.runtime, "read_config", dict)
    calls = []
    monkeypatch.setattr(w, "prepare", lambda *args, **kwargs: calls.append(kwargs))
    cli.dispatch(
        cli.parser().parse_args(
            [
                "knowledge",
                "prepare",
                "--ids-file",
                str(tmp_path / "ids"),
                "--vault",
                str(tmp_path),
                "--subdir",
                "Knowledge",
                "--delete-verified",
            ]
        )
    )
    assert calls[0]["with_outline"] is False
    assert calls[0]["cleanup_after"] == "article"
    assert calls[0]["delete_verified"] is True


def test_persisted_legacy_job_still_requires_outline(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    ids = tmp_path / "ids"
    ids.write_text("a")
    fake = FakeCLI([card("a")])
    monkeypatch.setattr(w, "run_json", fake)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    result = w.prepare(
        ids, vault, "Knowledge", "doc", state_root=tmp_path / "jobs", with_outline=True, delete_verified=True
    )
    job = Path(result["job"])
    # 构造旧版已保存的 spec：没有新字段，但原有大纲目标和授权保持。
    spec = json.loads((job / "spec.json").read_text())
    for key in ["kind", "with_outline", "cleanup_after"]:
        spec.pop(key)
    write(job / "spec.json", spec)
    state = json.loads((job / "job.json").read_text())
    state["sealed"]["spec.json"] = sha((job / "spec.json").read_bytes())
    write(job / "job.json", state)
    review = job / "review.json"
    write(review, review_for(result, vault))
    w.submit(str(job), review)
    assert w.publish(str(job))["delivery"] == "article-and-outline"
    assert fake.imports == 1
    assert w.cleanup(str(job), True)["status"] == "cleaned"


def test_article_knowledge_must_exist_before_cleanup(tmp_path, monkeypatch):
    fake, result, _vault, review = start(tmp_path, monkeypatch, delete_verified=True)
    w.submit(result["job"], review)
    with pytest.raises(WorkflowError, match="尚未登记"):
        w.cleanup(result["job"], True)
    assert fake.deletes == 0
