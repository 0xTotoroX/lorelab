import pytest
from soota.artifacts.bundle import content_from_markdown, write_bundle
from soota.errors import InputError
from soota.models import MediaItem, TranscriptDocument, TranscriptSegment, TranscriptSource
from soota.routing import recognize

from lorelab.content.analysis import AnalysisSubmission, render_analysis
from lorelab.content.models import Analysis, KeyPoint


def source(tmp_path):
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"))
    content = content_from_markdown(item.source, "Body paragraph")
    document = TranscriptDocument(
        status="ready",
        segments=[
            TranscriptSegment(
                segment_id="seg-000001",
                text="Caption",
                start_ms=0,
                end_ms=1000,
                source=TranscriptSource.OFFICIAL,
            )
        ],
    )
    return item, content, document, write_bundle(tmp_path, item, content=content, document=document)


def test_analysis_both_evidence_kinds_and_separate_linked_outputs(tmp_path):
    _, content, _, bundle = source(tmp_path)
    original = (tmp_path / "context.md").read_bytes()
    submission = AnalysisSubmission(
        context_fingerprint=bundle.context_fingerprint,
        task_id="task",
        item_id="item",
        analysis=Analysis(
            summary="Summary", key_points=[KeyPoint(text="Point", evidence=[content.blocks[0].block_id, "seg-000001"])]
        ),
        note_markdown="# Note\n\nNote body",
        outline_markdown="# Outline\n\n- Topic",
    )
    result = render_analysis(tmp_path, submission)
    assert result.analysis.status == "ready"
    assert f"context.md#{content.blocks[0].block_id}" in (tmp_path / "analysis.md").read_text()
    assert "transcript.md#seg-000001" in (tmp_path / "analysis.md").read_text()
    assert "[大纲](outline.md)" in (tmp_path / "note.md").read_text()
    assert "[笔记](note.md)" in (tmp_path / "outline.md").read_text()
    assert not (tmp_path / "content.md").exists()
    assert (tmp_path / "context.md").read_bytes() == original


def test_reject_stale_fingerprint_or_unknown_evidence_without_writing(tmp_path):
    _, _, _, bundle = source(tmp_path)
    with pytest.raises(InputError, match="变化"):
        render_analysis(tmp_path, AnalysisSubmission(context_fingerprint="stale", note_markdown="Note"))
    with pytest.raises(InputError, match="不存在"):
        render_analysis(
            tmp_path,
            AnalysisSubmission(
                context_fingerprint=bundle.context_fingerprint,
                analysis=Analysis(summary="Summary", key_points=[KeyPoint(text="Bad", evidence=["seg-999999"])]),
            ),
        )
    assert not (tmp_path / "analysis.json").exists()
    (tmp_path / "context.md").write_text("Manually edited source")
    with pytest.raises(InputError, match="变化"):
        render_analysis(
            tmp_path, AnalysisSubmission(context_fingerprint=bundle.context_fingerprint, note_markdown="Note")
        )


def test_reingest_preserves_analysis_marks_stale_and_rerender_needs_force(tmp_path):
    item, _, document, bundle = source(tmp_path)
    request = AnalysisSubmission(
        context_fingerprint=bundle.context_fingerprint, article_markdown="User requested article"
    )
    render_analysis(tmp_path, request)
    article = (tmp_path / "content.md").read_bytes()
    with pytest.raises(InputError, match="已存在"):
        render_analysis(tmp_path, request)
    changed = content_from_markdown(item.source, "Changed body")
    updated = write_bundle(tmp_path, item, document=document, content=changed, force=True)
    assert updated.analysis.status == "stale"
    assert (tmp_path / "content.md").read_bytes() == article
    render_analysis(
        tmp_path,
        AnalysisSubmission(context_fingerprint=updated.context_fingerprint, article_markdown="Explicit replacement"),
        force=True,
    )
    assert "Explicit replacement" in (tmp_path / "content.md").read_text()


def test_context_match_does_not_accept_changed_evidence_file(tmp_path):
    _, _, _, bundle = source(tmp_path)
    path = tmp_path / "transcript.md"
    path.write_text(path.read_text().replace("Caption", "Changed evidence"))
    with pytest.raises(InputError, match="字幕被修改"):
        render_analysis(
            tmp_path, AnalysisSubmission(context_fingerprint=bundle.context_fingerprint, note_markdown="Requested note")
        )
