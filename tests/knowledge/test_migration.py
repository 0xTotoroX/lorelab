"""LoreLab 工作流归属、独立 Soota 采集与旧任务保全。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from soota.artifacts.bundle import content_from_markdown, write_bundle
from soota.cli import app
from soota.models import MediaItem, TranscriptDocument, TranscriptSegment, TranscriptSource, TranscriptStatus
from soota.routing import recognize
from typer.testing import CliRunner

from lorelab.knowledge import runtime, workflow
from lorelab.knowledge.workflow_state import WorkflowError, default_root

from .support import FakeCLI, review_for, sha, write


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(("LORELAB_", "LOREHUB_", "SOOTA_KNOWLEDGE_")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("SOOTA_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SOOTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path


def make_bundle(path, *, transcript=False, scope="full", with_body=False):
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"), title="Synthetic source")
    if transcript:
        document = TranscriptDocument(
            status=TranscriptStatus.READY,
            source=TranscriptSource.OFFICIAL,
            segments=[
                TranscriptSegment(
                    text="Recorded sentence.",
                    segment_id="seg-one",
                    start_ms=0,
                    end_ms=1000,
                    source=TranscriptSource.OFFICIAL,
                )
            ],
        )
        content = content_from_markdown(item.source, "Body text beside the video.") if with_body else None
        write_bundle(path, item, document=document, content=content)
    else:
        content = content_from_markdown(item.source, "One supported point.\n\nIts condition.")
        content.scope = scope
        write_bundle(path, item, content=content)
    return path


@pytest.mark.parametrize("transcript", [False, True])
def test_bundle_to_article_never_calls_cubox_or_deletes_source(isolated, monkeypatch, transcript):
    source = make_bundle(isolated / "source", transcript=transcript)
    original = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
    paths = isolated / "bundles.json"
    write(paths, ["source", "source/manifest.json"])
    vault = isolated / "vault"
    vault.mkdir()
    fake = FakeCLI([])

    def invoke(tool, *args, **kwargs):
        assert tool == "lorelab", "bundle article flow must be independent of optional services"
        return fake(tool, *args, **kwargs)

    monkeypatch.setattr(workflow, "run_json", invoke)
    result = workflow.prepare(None, vault, "Knowledge", bundles_file=paths, delete_verified=True)
    assert len(result["sources"]) == 1
    assert not json.loads((Path(result["job"]) / "spec.json").read_text())["delete_verified"]
    review = Path(result["job"]) / "review.json"
    write(review, review_for(result, vault))
    workflow.submit(result["job"], review)
    assert workflow.publish(result["job"])["status"] == "verified"
    assert workflow.verify(result["job"])["status"] == "verified"
    assert workflow.cleanup(result["job"], True)["cleanup_preview"]["eligible_ids"] == []
    assert {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()} == original
    (source / "context.md").write_text("changed")
    with pytest.raises(WorkflowError, match="修改"):
        workflow.verify(result["job"])


def test_missing_bundle_evidence_fails_without_source_changes(isolated):
    source = make_bundle(isolated / "source")
    (source / "context.md").unlink()
    write(isolated / "bundles.json", [str(source)])
    vault = isolated / "vault"
    vault.mkdir()
    with pytest.raises(WorkflowError, match="产物不完整"):
        workflow.prepare(None, vault, "Knowledge", bundles_file=isolated / "bundles.json")
    assert not list(vault.iterdir())


def test_bundle_context_keeps_body_and_video_transcript(isolated, monkeypatch):
    source = make_bundle(isolated / "source", transcript=True, with_body=True)
    write(isolated / "bundles.json", [str(source)])
    vault = isolated / "vault"
    vault.mkdir()
    monkeypatch.setattr(workflow, "run_json", FakeCLI([]))
    result = workflow.prepare(None, vault, "Knowledge", bundles_file=isolated / "bundles.json")
    saved = Path(result["sources"][0]["source_path"]).read_text()
    assert saved == (source / "context.md").read_text()
    assert "Body text beside the video." in saved
    assert "Recorded sentence." in saved


def test_bundle_excerpt_cannot_be_claimed_complete(isolated, monkeypatch):
    source = make_bundle(isolated / "source", scope="excerpt")
    write(isolated / "bundles.json", [str(source)])
    vault = isolated / "vault"
    vault.mkdir()
    monkeypatch.setattr(workflow, "run_json", FakeCLI([]))
    result = workflow.prepare(None, vault, "Knowledge", bundles_file=isolated / "bundles.json")
    review = Path(result["job"]) / "review.json"
    write(review, review_for(result, vault))
    with pytest.raises(WorkflowError, match="节选"):
        workflow.submit(result["job"], review)


def test_product_owns_workflows_and_collection_imports_without_product(isolated):
    from lorelab.knowledge.cli import dispatch, parser

    settings = dispatch(parser().parse_args(["knowledge", "init", "--vault", str(isolated), "--subdir", "Knowledge"]))
    assert settings["settings"]["cleanup_after"] == "article"
    assert runtime.config_path() == isolated / "config/lorelab/config.json"
    source = Path(__file__).resolve().parents[2] / "modules/soota/src"
    subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            (
                "import soota, importlib.util, sys; "
                "assert importlib.util.find_spec('soota.knowledge') is None; "
                "assert importlib.util.find_spec('lorelab') is None"
            ),
        ],
        cwd=isolated,
        env={**os.environ, "PYTHONPATH": str(source)},
        check=True,
        capture_output=True,
    )
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "knowledge" not in result.stdout and "study" not in result.stdout


def test_config_fallback_keeps_legacy_authorization_and_explicit_isolation(isolated, monkeypatch):
    old = isolated / "config/lorehub/config.json"
    write(old, {"delete_verified": True})
    before = old.read_bytes()
    assert runtime.config_path() == old
    assert runtime.read_config() == {"delete_verified": True}
    assert old.read_bytes() == before
    monkeypatch.setenv("SOOTA_CONFIG_DIR", str(isolated / "explicit"))
    assert runtime.config_path() == isolated / "explicit/knowledge.json"
    assert runtime.read_config() == {}
    monkeypatch.setenv("SOOTA_KNOWLEDGE_CONFIG_FILE", str(isolated / "specific.json"))
    assert runtime.config_path() == isolated / "specific.json"


def test_state_paths_keep_explicit_legacy_directory(isolated, monkeypatch):
    assert default_root() == isolated / "data/knowledge/jobs"
    monkeypatch.setenv("LOREHUB_STATE_DIR", str(isolated / "legacy"))
    assert default_root() == isolated / "legacy"
    monkeypatch.setenv("SOOTA_KNOWLEDGE_STATE_DIR", str(isolated / "explicit"))
    assert default_root() == isolated / "explicit"


def test_new_workflow_state_uses_product_directory(isolated, monkeypatch):
    monkeypatch.delenv("SOOTA_DATA_DIR")
    assert default_root() == isolated / "state/lorelab/jobs"
    monkeypatch.setenv("LORELAB_STATE_DIR", str(isolated / "product"))
    monkeypatch.setenv("SOOTA_KNOWLEDGE_STATE_DIR", str(isolated / "legacy"))
    assert default_root() == isolated / "product"


def test_product_config_override_preserves_existing_legacy_file(isolated, monkeypatch):
    old = isolated / "config/soota/knowledge.json"
    write(old, {"delete_verified": True, "cleanup_after": "outline"})
    before = old.read_bytes()
    assert runtime.config_path() == old
    monkeypatch.setenv("LORELAB_CONFIG_FILE", str(isolated / "new/config.json"))
    assert runtime.read_config() == {}
    assert old.read_bytes() == before


def test_standalone_commands_are_argv_and_current_python(isolated, monkeypatch):
    assert runtime.tool_command("soota") == [sys.executable, "-m", "soota.cli"]
    monkeypatch.setenv("SOOTA_MUBU_COMMAND", json.dumps([sys.executable, "/script path/helper.py"]))
    assert runtime.tool_command("mubu") == [sys.executable, "/script path/helper.py"]
    monkeypatch.setenv("SOOTA_MUBU_COMMAND", "python3 script.py; echo wrong")
    with pytest.raises(runtime.ToolError, match="argv"):
        runtime.tool_command("mubu")


def test_managed_binding_never_falls_back_to_path(isolated, monkeypatch):
    lock = isolated / "components.lock.json"
    lock.write_text("{}")
    manifest = isolated / "runtime.json"
    write(
        manifest,
        {
            "schema_version": 1,
            "components_lock_sha256": sha(lock.read_bytes()),
            "tools": {"soota": [sys.executable, "-m", "soota.cli"]},
        },
    )
    monkeypatch.setenv("SOOTA_KNOWLEDGE_RUNTIME_FILE", str(manifest))
    monkeypatch.setenv("SOOTA_KNOWLEDGE_COMPONENTS_LOCK", str(lock))
    with pytest.raises(runtime.ToolError):
        runtime.tool_command("cubox")
    lock.write_text('{"changed":true}')
    with pytest.raises(runtime.ToolError, match="不一致"):
        runtime.tool_command("soota")


def test_managed_runtime_cannot_point_at_another_same_lock_install(isolated, monkeypatch):
    lock = isolated / "components.lock.json"
    lock.write_text("{}")
    manifest = isolated / "runtime.json"
    write(
        manifest,
        {
            "schema_version": 1,
            "components_lock_sha256": sha(lock.read_bytes()),
            "source_root": str(isolated / "another-install"),
            "tools": {"soota": [sys.executable, "-m", "soota.cli"]},
        },
    )
    monkeypatch.setenv("SOOTA_KNOWLEDGE_RUNTIME_FILE", str(manifest))
    monkeypatch.setenv("SOOTA_KNOWLEDGE_COMPONENTS_LOCK", str(lock))
    with pytest.raises(runtime.ToolError, match="路径绑定不一致"):
        runtime.tool_command("soota")
