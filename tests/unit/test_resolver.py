from pathlib import Path

from soota.models import TranscriptMode, TranscriptSegment, TranscriptSource
from soota.pipeline import ingest
from tests.conftest import load_fixture


class FakeAsr:
    name = "fake"

    def transcribe(self, audio: Path, *, language: str | None):
        return [
            TranscriptSegment(
                segment_id="seg-000001",
                start_ms=0,
                end_ms=1000,
                text="asr text",
                language=language,
                source=TranscriptSource.ASR,
            )
        ]


def _youtube_requester(missing: bool = False):
    calls: list[str] = []

    def requester(method: str, path: str, params: dict):
        calls.append(path)
        if path.endswith("get_video_info_v2"):
            return load_fixture("youtube_info.json")
        if path.endswith("get_video_captions"):
            if missing:
                return load_fixture("youtube_captions_missing.json")
            if not params.get("language_code"):
                return load_fixture("youtube_captions_list.json")
            return load_fixture("youtube_captions_srt.json")
        if path.endswith("get_video_streams_v2"):
            return load_fixture("youtube_streams.json")
        raise AssertionError(path)

    requester.calls = calls  # type: ignore[attr-defined]
    return requester


def test_captions_preferred_and_no_asr(settings, tmp_path) -> None:
    requester = _youtube_requester(missing=False)

    def http_get(url: str):  # pragma: no cover
        raise AssertionError("cdn not used for captions")

    result = ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        provider="tikhub",
        transcript=TranscriptMode.AUTO,
        requester=requester,
        asr=FakeAsr(),
        audio_provider="tikhub",
    )
    assert result.exit_code == 0
    assert result.data["transcript_source"] == TranscriptSource.OFFICIAL
    assert not any("streams" in c for c in requester.calls)


def test_missing_captions_runs_asr(settings, monkeypatch) -> None:
    requester = _youtube_requester(missing=True)

    class Resp:
        def __init__(self, content: bytes):
            self.content = content

        def json(self):
            return {}

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str) -> Resp:
        return Resp(b"audio-bytes")

    from soota.providers.tikhub import client as client_mod

    original_init = client_mod.TikHubProvider.__init__

    def wrapped(self, *args, **kwargs):
        kwargs.setdefault("http_get", fake_get)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(client_mod.TikHubProvider, "__init__", wrapped)
    result = ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        provider="tikhub",
        transcript=TranscriptMode.AUTO,
        requester=requester,
        asr=FakeAsr(),
        audio_provider="tikhub",
    )
    assert result.data["transcript_source"] == TranscriptSource.ASR
    assert any("streams" in c for c in requester.calls)


def test_second_run_is_cache_hit(settings) -> None:
    requester = _youtube_requester()
    ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        requester=requester,
        asr=FakeAsr(),
        audio_provider="tikhub",
        max_cost=0.1,
        provider="tikhub",
    )
    first = list(requester.calls)
    requester.calls.clear()
    result = ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        requester=requester,
        asr=FakeAsr(),
        audio_provider="tikhub",
        max_cost=0.1,
        provider="tikhub",
    )
    assert result.data["cache_hit"] is True
    assert requester.calls == []
    assert first


def _bili_requester(*, empty_subtitles: bool = False):
    from tests.conftest import load_fixture

    calls: list[str] = []
    info = load_fixture("bilibili_info.json")
    if empty_subtitles:
        info = {
            "code": 200,
            "data": {
                "View": {
                    **info["data"]["View"],
                    "subtitle": {"list": []},
                }
            },
        }

    def requester(method: str, path: str, params: dict):
        calls.append(path)
        if path.endswith("fetch_one_video_v3"):
            assert "url" in params and "bv_id" not in params
            return info
        if path.endswith("fetch_video_subtitle"):
            return {"code": 200, "data": {"subtitles": []}}
        if path.endswith("fetch_video_playurl"):
            return load_fixture("youtube_streams.json")
        raise AssertionError(path)

    requester.calls = calls  # type: ignore[attr-defined]
    return requester


def test_bili_inspect_tracks_skip_paid_subtitle(settings, monkeypatch) -> None:
    from tests.conftest import load_fixture

    requester = _bili_requester()

    class Resp:
        def json(self):
            return load_fixture("bilibili_subtitle_body.json")

        def raise_for_status(self) -> None:
            return None

        content = b"{}"

    from soota.providers.tikhub import client as client_mod

    original_init = client_mod.TikHubProvider.__init__

    def wrapped(self, *args, **kwargs):
        kwargs.setdefault("http_get", lambda url: Resp())
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(client_mod.TikHubProvider, "__init__", wrapped)
    result = ingest(
        settings,
        "https://www.bilibili.com/video/BV1M1421t7hT",
        provider="tikhub",
        transcript=TranscriptMode.AUTO,
        requester=requester,
        asr=FakeAsr(),
        audio_provider="tikhub",
    )
    assert result.data["transcript_source"] == TranscriptSource.OFFICIAL
    assert not any("subtitle" in c for c in requester.calls)
    content = Path(result.data["content"]).read_text(encoding="utf-8")
    assert "## 正文" in content
    assert "你好世界" in content or "你好" in content


def test_bili_empty_inspect_still_probes_subtitle(settings, monkeypatch) -> None:
    requester = _bili_requester(empty_subtitles=True)

    class Resp:
        def __init__(self, content: bytes = b"audio-bytes"):
            self.content = content

        def json(self):
            return {}

        def raise_for_status(self) -> None:
            return None

    from soota.providers.tikhub import client as client_mod

    original_init = client_mod.TikHubProvider.__init__

    def wrapped(self, *args, **kwargs):
        kwargs.setdefault("http_get", lambda url: Resp())
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(client_mod.TikHubProvider, "__init__", wrapped)
    result = ingest(
        settings,
        "https://www.bilibili.com/video/BV1M1421t7hT",
        provider="tikhub",
        transcript=TranscriptMode.AUTO,
        requester=requester,
        asr=FakeAsr(),
        audio_provider="tikhub",
    )
    assert any("fetch_video_subtitle" in c for c in requester.calls)
    assert result.data["transcript_status"] == "unknown"
    assert not any("playurl" in c for c in requester.calls)


def test_audio_falls_back_to_ytdlp(settings, monkeypatch) -> None:
    requester = _youtube_requester(missing=True)

    def fake_ytdlp(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"abc")
        return dest

    monkeypatch.setattr("soota.providers.tikhub.client.fetch_audio_ytdlp", fake_ytdlp)
    monkeypatch.setattr(
        "soota.providers.tikhub.client.TikHubProvider._download",
        lambda self, url, dest: (_ for _ in ()).throw(RuntimeError("cdn fail")),
    )
    result = ingest(
        settings,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        provider="tikhub",
        transcript=TranscriptMode.AUTO,
        requester=requester,
        asr=FakeAsr(),
        audio_provider="tikhub",
    )
    assert result.data["transcript_source"] == TranscriptSource.ASR
    assert any(r["endpoint"] == "local:yt-dlp" for r in result.data["requests"])
    assert result.data["audio_provider"] == "yt-dlp"
    assert result.data["audio_provider_requested"] == "tikhub"
