import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from soota.cli import app
from soota.tasks import runner
from soota.tasks.entry import ingest
from soota.tasks.runner import resume
from soota.tasks.state import _bundle_lock
from typer.testing import CliRunner

from lorelab.content import tasks as content_tasks


def local_batch(tmp_path, count):
    paths = [tmp_path / f"source-{i}.txt" for i in range(count)]
    for i, path in enumerate(paths):
        path.write_text(f"Source {i}.\n\nEvidence {i}.\n")
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps([str(path) for path in paths]))
    return inputs, paths


def test_dry_run_has_no_task_or_output_writes(settings, article):
    result = ingest(settings, str(article), want="context,note", dry_run=True)
    assert result.ok and not settings.jobs_dir.exists() and not settings.output_dir.exists()


def test_analysis_waits_and_resumes_with_matching_identity(settings, article, tmp_path):
    result = ingest(settings, str(article), want="context,note")
    assert not result.ok and result.data["job_status"] == "waiting_analysis"
    folder = Path(result.data["output"])
    request = json.loads((folder / "analysis-request.json").read_text())
    submission = tmp_path / "submission.json"
    submission.write_text(
        json.dumps(
            {
                "task_id": request["task_id"],
                "item_id": request["item_id"],
                "context_fingerprint": request["context_fingerprint"],
                "note_markdown": "# Note\n\nA supported note.",
            }
        )
    )
    done = resume(settings, result.data["job_id"], analysis=submission)
    assert done.ok, done.model_dump()
    assert (folder / "note.md").exists()
    assert resume(settings, result.data["job_id"], analysis=submission).ok


def test_wrong_task_analysis_never_writes(settings, article, tmp_path):
    result = ingest(settings, str(article), want="note")
    folder = Path(result.data["output"])
    request = json.loads((folder / "analysis-request.json").read_text())
    path = tmp_path / "wrong.json"
    path.write_text(
        json.dumps(
            {
                "task_id": "different",
                "item_id": request["item_id"],
                "context_fingerprint": request["context_fingerprint"],
                "note_markdown": "wrong",
            }
        )
    )
    assert not resume(settings, result.data["job_id"], analysis=path).ok
    assert not (folder / "note.md").exists()


def test_analysis_goal_can_complete_without_a_reading_article(settings, article, tmp_path):
    first = ingest(settings, str(article), want="analysis,outline")
    assert first.data["job_status"] == "waiting_analysis"
    folder = Path(first.data["output"])
    request = json.loads((folder / "analysis-request.json").read_text())
    submission = tmp_path / "analysis-submission.json"
    submission.write_text(
        json.dumps(
            {
                "task_id": request["task_id"],
                "item_id": request["item_id"],
                "context_fingerprint": request["context_fingerprint"],
                "analysis": {"summary": "Supported summary"},
                "outline_markdown": "# Outline\n\n- One topic",
            }
        )
    )
    result = resume(settings, first.data["job_id"], analysis=submission)
    assert result.ok, result.model_dump()
    assert (folder / "analysis.md").is_file() and (folder / "outline.md").is_file()
    assert not (folder / "content.md").exists()


def test_distinct_bundles_with_same_export_target_are_serialized(settings, tmp_path, monkeypatch):
    inputs, paths = local_batch(tmp_path, 1)
    first = ingest(settings, str(paths[0]), want="context")
    first_bundle = Path(first.data["output"])
    other_bundle = tmp_path / "copied-bundle"
    shutil.copytree(first_bundle, other_bundle)
    inputs.write_text(json.dumps([str(first_bundle), str(other_bundle)]))
    export = content_tasks.export_bundle
    lock = threading.Lock()
    active = peak = 0

    def slow_export(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(active, peak)
        try:
            time.sleep(0.05)
            return export(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(content_tasks, "export_bundle", slow_export)
    result = ingest(settings, inputs_file=inputs, want="context", workers=2, destination=tmp_path / "export")
    assert result.ok, result.model_dump()
    assert peak == 1
    targets = {row["data"]["export"] for row in result.data["items"]}
    assert len(targets) == 1
    assert (Path(targets.pop()) / "context.md").is_file()


def test_export_cannot_write_a_destination_in_use_as_another_bundle(settings, tmp_path):
    _, paths = local_batch(tmp_path, 1)
    first = ingest(settings, str(paths[0]), want="context", destination=tmp_path / "export")
    assert first.ok
    target = Path(first.data["export"])
    before = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
    with _bundle_lock(target):
        result = ingest(settings, str(paths[0]), want="context", workers=2, destination=tmp_path / "export")
    assert result.data["job_status"] == "partial"
    assert result.data["items"][0]["steps"]["export"]["status"] == "failed"
    assert {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()} == before


def test_parallel_note_outline_handoff_directory_and_idempotent_cli_resume(settings, tmp_path, monkeypatch):
    inputs, paths = local_batch(tmp_path, 3)
    originals = [path.read_bytes() for path in paths]
    monkeypatch.setattr("soota.config.load_settings", lambda: settings)
    cli = CliRunner()
    first = cli.invoke(
        app,
        [
            "ingest",
            "--inputs-file",
            str(inputs),
            "--provider",
            "local",
            "--want",
            "context,note,outline",
            "--workers",
            "2",
            "--max-cost",
            "0",
            "--json",
        ],
    )
    result = json.loads(first.stdout)
    assert first.exit_code == 2 and result["data"]["job_status"] == "waiting_analysis"
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    contexts = {}
    for i, row in enumerate(result["data"]["items"]):
        folder = Path(row["bundle"])
        request = json.loads((folder / "analysis-request.json").read_text())
        assert request["item_id"] == row["item_id"]
        assert request["requested_outputs"] == ["note", "outline"]
        manifest = json.loads((folder / "manifest.json").read_text())
        evidence = manifest["content"]["blocks"][0]["block_id"]
        contexts[folder] = (folder / "context.md").read_bytes()
        payload = {key: request[key] for key in ("task_id", "item_id", "context_fingerprint")}
        payload.update(
            note_markdown=f"# Note {i}\n\nSource {i}. [evidence](context.md#{evidence})",
            outline_markdown=f"# Outline {i}\n\n- Source {i}. [evidence](context.md#{evidence})",
        )
        (submissions / f"{row['item_id']}.json").write_text(json.dumps(payload))
    monkeypatch.setattr(runner, "collect_text", lambda *a, **k: pytest.fail("resume reacquired saved source"))
    args = ["jobs", "resume", result["data"]["job_id"], "--analysis", str(submissions), "--workers", "3", "--json"]
    for _ in range(2):
        done = cli.invoke(app, args)
        assert done.exit_code == 0, done.output
        saved = json.loads(done.stdout)
        assert saved["data"]["reserved_cost_usd"] == 0
        assert all(row["status"] == "completed" for row in saved["data"]["items"])
    for folder, context in contexts.items():
        assert (folder / "context.md").read_bytes() == context
        assert (folder / "note.md").is_file() and (folder / "outline.md").is_file()
        assert not (folder / "content.md").exists()
    assert [path.read_bytes() for path in paths] == originals
