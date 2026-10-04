import json
from pathlib import Path

import pytest

from soota.errors import InputError
from soota.models import (
    AnalysisStatus,
    ContentBundleManifest,
    MediaItem,
    TranscriptDocument,
    TranscriptManifest,
    TranscriptSegment,
    TranscriptSource,
    TranscriptStatus,
)
from soota.pipeline import _document_from_transcript_md, render
from soota.render.bundle import write_bundle
from soota.routing import recognize


def source_bundle(tmp_path, *, text="先说这个\n这个", start=250):
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"), title="Example")
    segments = [
        TranscriptSegment(
            segment_id="seg-000001", start_ms=start, end_ms=1500, text=text, source=TranscriptSource.AUTO
        ),
        TranscriptSegment(
            segment_id="seg-000002", start_ms=1600, end_ms=2250, text="先说这个", source=TranscriptSource.AUTO
        ),
    ]
    document = TranscriptDocument(
        status=TranscriptStatus.READY, source=TranscriptSource.AUTO, language="zh", segments=segments
    )
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=document.status))
    folder = write_bundle(tmp_path, item, document, manifest, None)
    return folder, item, document, manifest


def analysis_file(folder, summary="Explicit analysis"):
    path = folder / "requested-analysis.json"
    path.write_text(json.dumps({"summary": summary, "key_points": [{"text": "point", "evidence": ["seg-000001"]}]}))
    return path


def test_default_bundle_is_context_only_and_keeps_cue_text(tmp_path):
    folder, _, _, manifest = source_bundle(tmp_path)
    text = (folder / "context.md").read_text()
    assert "[seg-000001] 先说这个\n这个\n[seg-000002] 先说这个" in text
    assert "## 摘要" not in text and "尚未生成分析" not in text
    assert not (folder / "content.md").exists()
    assert manifest.analysis.status == AnalysisStatus.NOT_REQUESTED and manifest.analysis.path is None
    assert set(manifest.files) == {"context.md", "transcript.md", "manifest.json"}
    transcript = (folder / "transcript.md").read_text()
    assert "00:00:00.250-00:00:01.500" in transcript
    restored = _document_from_transcript_md(folder / "transcript.md", manifest)
    assert restored.segments[0].start_ms == 250 and restored.segments[0].end_ms == 1500
    assert restored.segments[0].text == "先说这个\n这个"


def test_render_only_writes_explicit_analysis_and_never_rewrites_context(settings, tmp_path):
    folder, *_ = source_bundle(tmp_path)
    original = {name: (folder / name).read_bytes() for name in ("context.md", "transcript.md")}
    (folder / "transcript.original.md").write_text("Unfiltered source")
    result = render(settings, bundle=folder, analysis=analysis_file(folder))
    assert Path(result.data["content"]).name == "content.md"
    assert "Explicit analysis" in (folder / "content.md").read_text()
    for name, data in original.items():
        assert (folder / name).read_bytes() == data
    assert (folder / "transcript.original.md").read_text() == "Unfiltered source"


def test_render_honors_force_for_existing_user_article(settings, tmp_path):
    folder, *_ = source_bundle(tmp_path)
    (folder / "content.md").write_text("User edited article")
    before = {name: (folder / name).read_bytes() for name in ("context.md", "transcript.md", "manifest.json")}
    analysis = analysis_file(folder)
    with pytest.raises(InputError, match="--force|已存在"):
        render(settings, bundle=folder, analysis=analysis)
    assert (folder / "content.md").read_text() == "User edited article"
    assert all((folder / name).read_bytes() == data for name, data in before.items())
    render(settings, bundle=folder, analysis=analysis, force=True)
    assert "Explicit analysis" in (folder / "content.md").read_text()
    for name in ("context.md", "transcript.md"):
        assert (folder / name).read_bytes() == before[name]


@pytest.mark.parametrize("force", [False, True])
def test_reingest_preserves_user_article_and_ready_status(settings, tmp_path, force):
    folder, item, document, _ = source_bundle(tmp_path)
    render(settings, bundle=folder, analysis=analysis_file(folder))
    (folder / "content.md").write_text("User edited article")
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=document.status))
    write_bundle(tmp_path, item, document, manifest, None, force=force)
    assert (folder / "content.md").read_text() == "User edited article"
    assert manifest.analysis.status == AnalysisStatus.READY and manifest.analysis.path == "content.md"


def test_changed_source_marks_old_article_stale_without_rewriting(settings, tmp_path):
    folder, *_ = source_bundle(tmp_path)
    render(settings, bundle=folder, analysis=analysis_file(folder))
    old_article = (folder / "content.md").read_bytes()
    _, _, _, manifest = source_bundle(tmp_path, text="New source text")
    assert "New source text" in (folder / "context.md").read_text()
    assert (folder / "content.md").read_bytes() == old_article
    assert manifest.analysis.status == AnalysisStatus.STALE and manifest.processing.warnings


def test_legacy_bundle_can_render_without_context_and_keeps_old_transcript(settings, tmp_path):
    folder, _, _, manifest = source_bundle(tmp_path)
    (folder / "context.md").unlink()
    old = (folder / "transcript.md").read_text().replace("00:00:00.250-00:00:01.500", "00:00:00-00:00:01")
    (folder / "transcript.md").write_text(old)
    manifest.files.pop("context.md")
    (folder / "manifest.json").write_text(manifest.model_dump_json())
    result = render(settings, bundle=folder, analysis=analysis_file(folder))
    assert result.data["context"] is None and not (folder / "context.md").exists()
    assert (folder / "transcript.md").read_text() == old


@pytest.mark.parametrize("status", [TranscriptStatus.MISSING, TranscriptStatus.UNKNOWN, TranscriptStatus.NOT_REQUESTED])
def test_empty_context_reports_real_state_without_an_article(tmp_path, status):
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"))
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=status))
    folder = write_bundle(tmp_path, item, TranscriptDocument(status=status), manifest, None)
    context = (folder / "context.md").read_text()
    assert f"transcript_status: {status.value}" in context
    assert "[seg-" not in context and not (folder / "content.md").exists()


@pytest.mark.parametrize(
    "status",
    [TranscriptStatus.MISSING, TranscriptStatus.UNKNOWN, TranscriptStatus.PENDING, TranscriptStatus.NOT_REQUESTED],
)
def test_empty_new_attempt_never_clears_saved_source(tmp_path, status):
    from soota.errors import SourcePreserved

    folder, item, _, _ = source_bundle(tmp_path)
    before = {name: (folder / name).read_bytes() for name in ("context.md", "transcript.md", "manifest.json")}
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=status))
    with pytest.raises(SourcePreserved) as exc:
        write_bundle(tmp_path, item, TranscriptDocument(status=status), manifest, None)
    assert exc.value.details["attempt_status"] == status.value
    assert all((folder / name).read_bytes() == data for name, data in before.items())


def test_legacy_timestamp_spelling_does_not_make_analysis_stale(settings, tmp_path):
    folder, item, document, _ = source_bundle(tmp_path, start=0)
    document.segments[0].end_ms = 1000
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=document.status))
    write_bundle(tmp_path, item, document, manifest, None)
    render(settings, bundle=folder, analysis=analysis_file(folder))
    path = folder / "transcript.md"
    path.write_text(path.read_text().replace("00:00:00.000-00:00:01.000", "00:00:00-00:00:01"))
    fresh = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=document.status))
    write_bundle(tmp_path, item, document, fresh, None)
    assert fresh.analysis.status == AnalysisStatus.READY


def test_explicit_rerender_removes_only_stale_warning(settings, tmp_path):
    from soota.render.bundle import STALE_WARNING

    folder, *_ = source_bundle(tmp_path)
    render(settings, bundle=folder, analysis=analysis_file(folder))
    _, _, _, manifest = source_bundle(tmp_path, text="changed")
    manifest.processing.warnings.append("keep this unrelated warning")
    (folder / "manifest.json").write_text(manifest.model_dump_json())
    render(settings, bundle=folder, analysis=analysis_file(folder), force=True)
    saved = ContentBundleManifest.model_validate_json((folder / "manifest.json").read_text())
    assert saved.analysis.status == AnalysisStatus.READY
    assert STALE_WARNING not in saved.processing.warnings
    assert "keep this unrelated warning" in saved.processing.warnings


def test_explicit_analysis_can_create_a_fresh_bundle_with_source(tmp_path):
    from soota.models import Analysis

    _, item, document, _ = source_bundle(tmp_path / "input")
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=document.status))
    folder = write_bundle(tmp_path / "new", item, document, manifest, Analysis(summary="Requested summary"))
    assert all((folder / name).is_file() for name in ("context.md", "transcript.md", "content.md", "manifest.json"))
    assert manifest.analysis.status == AnalysisStatus.READY
    assert manifest.transcript.segments == len(document.segments)


@pytest.mark.parametrize("provider", ["opencli", "tikhub"])
def test_ingest_returns_context_for_both_paths_without_article(settings, monkeypatch, provider):
    from soota.models import CaptionResult, TranscriptMode
    from soota.pipeline import ingest
    from soota.providers.opencli import OpenCLIProvider
    from tests.unit.test_resolver import _youtube_requester

    _, sample, document, _ = source_bundle(settings.output_dir / "fixture")
    monkeypatch.setattr(
        OpenCLIProvider, "inspect", lambda self, source: MediaItem(source=source, provenance={"provider": "opencli"})
    )
    monkeypatch.setattr(
        OpenCLIProvider,
        "get_captions",
        lambda *a: CaptionResult(status=TranscriptStatus.READY, segments=document.segments),
    )
    result = ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        provider=provider,
        transcript=TranscriptMode.CAPTIONS_ONLY,
        requester=_youtube_requester(),
        max_cost=0.1,
    )
    assert result.ok
    assert result.data["context"] == result.data["content"]
    assert Path(result.data["context"]).name == "context.md" and Path(result.data["context"]).is_file()
    assert not (Path(result.data["output"]) / "content.md").exists()
    assert result.data["analysis"] == {"status": "not_requested", "path": None}
