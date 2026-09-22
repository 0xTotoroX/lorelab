import json
from pathlib import Path

from soota.errors import InputError
from soota.models import TranscriptMode
from soota.pipeline import ingest, render
from tests.unit.test_resolver import FakeAsr, _youtube_requester


def test_render_writes_evidence_links(settings) -> None:
    result = ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        provider="tikhub",
        transcript=TranscriptMode.AUTO,
        max_cost=0.1,
        requester=_youtube_requester(),
        asr=FakeAsr(),
    )
    folder = Path(result.data["output"])
    analysis = {
        "schema_version": 1,
        "summary": "一首经典歌曲。",
        "key_points": [{"text": "开场歌词", "evidence": ["seg-000001"]}],
        "chapters": [{"title": "Intro", "start_ms": 0, "end_ms": 2000, "summary": "开头"}],
        "tags": ["music"],
        "language": "en",
    }
    analysis_path = folder / "analysis.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    rendered = render(settings, bundle=folder / "manifest.json", analysis=analysis_path)
    content = Path(rendered.data["content"]).read_text(encoding="utf-8")
    assert "seg-000001" in content
    assert "transcript.md#seg-000001" in content
    assert "一首经典歌曲" in content
    assert "## 正文" in content


def test_invalid_analysis_does_not_clobber(settings) -> None:
    result = ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        max_cost=0.1,
        requester=_youtube_requester(),
        asr=FakeAsr(),
    )
    folder = Path(result.data["output"])
    original = (folder / "content.md").read_text(encoding="utf-8")
    bad = folder / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    try:
        render(settings, bundle=folder, analysis=bad)
    except InputError:
        pass
    else:
        raise AssertionError("expected InputError")
    assert (folder / "content.md").read_text(encoding="utf-8") == original
