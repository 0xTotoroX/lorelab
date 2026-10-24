import importlib.util
import json
from pathlib import Path

import pytest
from soota.errors import InputError
from soota.storage.jobs import JobStore
from soota.tasks.entry import ingest as source_ingest
from soota.tasks.runner import resume as old_resume
from soota.tasks.state import task_folder
from typer.testing import CliRunner

from lorelab.content import api
from lorelab.content.cli import app


def test_source_acquisition_without_lorelab_and_old_command_stops_before_writes(settings, article, monkeypatch):
    original = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "lorelab" else original(name, *a))
    result = source_ingest(settings, str(article), want="context", provider="local")
    folder = Path(result.data["output"])
    assert result.ok and not (folder / "analysis-request.json").exists()
    before = {p: p.read_bytes() for p in settings.data_dir.rglob("*") if p.is_file()}
    with pytest.raises(InputError, match="LoreLab"):
        source_ingest(settings, str(article), want="note", provider="local")
    assert {p: p.read_bytes() for p in settings.data_dir.rglob("*") if p.is_file()} == before


def test_content_cli_directly_owns_semantic_task(settings, article, monkeypatch):
    settings.updates.enabled = True
    monkeypatch.setattr(
        "soota.auto_updates.automatic_update", lambda *a, **k: pytest.fail("offline task updated providers")
    )
    monkeypatch.setattr("soota.config.load_settings", lambda: settings)
    cli = CliRunner()
    result = cli.invoke(app, ["ingest", str(article), "--provider", "local", "--want", "note", "--json"])
    assert result.exit_code == 2, result.output
    data = json.loads(result.stdout)["data"]
    request = json.loads((task_folder(settings, data["job_id"]) / "request.json").read_text())
    assert request["owner"] == "lorelab"
    bundle = Path(data["items"][0]["bundle"])
    handoff = json.loads((bundle / "analysis-request.json").read_text())
    assert handoff["resume"].startswith("lorelab content resume ")
    payload = {k: handoff[k] for k in ("task_id", "item_id", "context_fingerprint")}
    submission = article.parent / "submission.json"
    submission.write_text(json.dumps({**payload, "note_markdown": "A requested note."}))
    before = (bundle / "context.md").read_bytes()
    monkeypatch.setattr("soota.tasks.runner.collect_text", lambda *a, **k: pytest.fail("reacquired source"))
    result = cli.invoke(app, ["resume", data["job_id"], "--analysis", str(submission), "--json"])
    assert result.exit_code == 0, result.output
    assert (bundle / "context.md").read_bytes() == before
    assert (bundle / "note.md").is_file()
    # The compatibility entry must recognize the owner before loading the source-only schema.
    from soota.cli import app as old_app

    result = cli.invoke(old_app, ["jobs", "resume", data["job_id"], "--json"])
    assert result.exit_code == 0, result.output


def test_old_request_and_frozen_handoff_survive_resume(settings, article):
    # Fixed old schema: source task gains the legacy note target, no owner field.
    first = source_ingest(settings, str(article), want="context", provider="local")
    job_id = first.data["job_id"]
    folder = Path(first.data["output"])
    request_path = task_folder(settings, job_id) / "request.json"
    spec = json.loads(request_path.read_text())
    spec["outputs"].append({"kind": "note", "required": True})
    assert "owner" not in spec
    request_path.write_text(json.dumps(spec))
    row = first.data["items"][0]
    manifest = json.loads((folder / "manifest.json").read_text())
    identity = {"task_id": job_id, "item_id": row["item_id"], "context_fingerprint": manifest["context_fingerprint"]}
    old_handoff = {
        **identity,
        "requested_outputs": ["note"],
        "context": str(folder / "context.md"),
        "resume": f"soota jobs resume {job_id} --analysis <submission.json> --json",
    }
    frozen = json.dumps(old_handoff, ensure_ascii=False, indent=4).encode()
    (folder / "analysis-request.json").write_bytes(frozen)
    original = (folder / "context.md").read_bytes()
    pending = old_resume(settings, job_id)
    assert pending.code == "waiting_analysis"
    assert (folder / "analysis-request.json").read_bytes() == frozen
    submission = article.parent / "submission.json"
    submission.write_text(json.dumps({**identity, "note_markdown": "Supported note."}))
    for _ in range(2):
        done = old_resume(settings, job_id, analysis=submission)
        assert done.ok, done.model_dump()
        assert done.data["job_id"] == job_id and done.data["items"][0]["item_id"] == row["item_id"]
        assert (folder / "analysis-request.json").read_bytes() == frozen
        assert (folder / "context.md").read_bytes() == original
    assert len(JobStore(settings.jobs_dir).list_jobs()) == 1


def test_changed_local_input_cannot_receive_old_analysis(settings, article):
    first = api.ingest(settings, str(article), want="note", provider="local")
    folder = Path(first.data["output"])
    handoff = json.loads((folder / "analysis-request.json").read_text())
    payload = {k: handoff[k] for k in ("task_id", "item_id", "context_fingerprint")}
    submission = article.parent / "submission.json"
    submission.write_text(json.dumps({**payload, "note_markdown": "Old analysis."}))
    article.write_text("Changed source.")
    result = api.resume(settings, first.data["job_id"], analysis=submission)
    assert not result.ok
    assert not (folder / "note.md").exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_online_content_updates_once_and_dry_run_never_updates(settings, monkeypatch, legacy):
    from soota.cli import app as old_app

    settings.updates.enabled = True
    monkeypatch.setattr("soota.config.load_settings", lambda: settings)
    calls = []

    def update(config):
        calls.append(config)
        return {"providers": [], "warnings": []}

    monkeypatch.setattr("soota.auto_updates.automatic_update", update)
    # Scope this test to update routing, with no provider/network work.
    monkeypatch.setattr("soota.tasks.runner.execute", lambda *a, **k: None)
    cli = CliRunner()
    args = ["ingest", "https://example.org/source", "--want", "note", "--json"]
    target = old_app if legacy else app
    result = cli.invoke(target, [*args, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert not calls and not settings.jobs_dir.exists()
    result = cli.invoke(target, args)
    assert result.exit_code == 0, result.output
    assert calls == [settings]


def test_product_content_entry_reports_usage_without_traceback(capsys):
    from lorelab.cli import main

    assert main(["content", "resume"]) == 2
    output = capsys.readouterr()
    assert "job_id" in output.err.lower() and "Traceback" not in output.err
