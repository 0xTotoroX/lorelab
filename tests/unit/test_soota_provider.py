import json
from pathlib import Path

import pytest

from soota.errors import AuthBudgetError, CaptionUnavailable, ContractError, SourceError
from soota.models import MediaItem, TranscriptMode, TranscriptSource
from soota.pipeline import estimate, ingest
from soota.providers.opencli import OpenCLIProvider
from soota.providers.opencli_runtime import RuntimeUnavailable
from soota.providers.process import ProcessResult
from soota.providers.router import catalog_provider, inspect_item
from soota.providers.soota import SootaProvider, select_track
from soota.routing import recognize

URL = "https://www.youtube.com/watch?v=--Example01&t=16s"
INFO = {
    "id": "--Example01",
    "title": "Example",
    "channel": "Sample channel",
    "duration": 2,
    "subtitles": {"zh": [{"ext": "json3", "url": "https://example.invalid/?secret=hidden"}]},
    "automatic_captions": {"en": [{"ext": "json3"}]},
}
BODY = {"events": [{"tStartMs": 100, "dDurationMs": 900, "segs": [{"utf8": "字幕"}, {"utf8": "内容"}]}]}


def stub_process(monkeypatch, *, info=None, body=None, error=None):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if error:
            return ProcessResult(1, "", error)
        if "--dump-single-json" in argv:
            return ProcessResult(0, json.dumps(INFO if info is None else info), "")
        template = argv[argv.index("-o") + 1]
        Path(template.replace("%(ext)s", "zh.json3")).write_text(json.dumps(BODY if body is None else body))
        return ProcessResult(0, "", "")

    monkeypatch.setattr("soota.providers.soota.shutil.which", lambda _: "/test/yt-dlp")
    monkeypatch.setattr("soota.providers.soota.run_process", run)
    return calls


def test_explicit_soota_downloads_only_selected_captions_and_reuses_cache(settings, monkeypatch):
    calls = stub_process(monkeypatch)
    result = ingest(settings, URL, provider="soota", transcript=TranscriptMode.CAPTIONS_ONLY, max_cost=0)
    manifest = json.loads(Path(result.data["manifest"]).read_text())
    assert result.ok and result.data["provider"] == "soota"
    assert manifest["transcript"]["language"] == "zh" and manifest["transcript"]["source"] == "official"
    assert manifest["processing"]["estimated_cost_usd"] == 0
    assert result.data["routing"]["attempted"] == ["soota"]
    assert len(calls) == 2
    for call in calls:
        assert "--ignore-config" in call and "--skip-download" in call and "--no-playlist" in call
        assert call[-2:] == ["--", recognize(URL).canonical_url]
    assert "--write-subs" in calls[1] and "--no-write-auto-subs" in calls[1]
    assert all("hidden" not in file.read_text() for file in settings.cache_dir.rglob("*.json"))
    cached = ingest(settings, URL, provider="soota", max_cost=0, force=True)
    assert cached.ok and cached.data["cache_hit"] and len(calls) == 2


@pytest.mark.parametrize("failure", [CaptionUnavailable("empty response"), RuntimeUnavailable("bridge absent"), None])
def test_auto_tries_soota_after_opencli_before_any_paid_request(settings, monkeypatch, failure):
    calls = stub_process(monkeypatch)

    def command(self, site, command, args):
        if command == "video":
            return [{"field": "videoId", "value": "--Example01"}, {"field": "title", "value": "Example"}]
        if failure:
            raise failure
        return []

    monkeypatch.setattr(OpenCLIProvider, "_run", command)
    result = ingest(settings, URL, max_cost=0)
    assert result.ok and result.data["routing"]["attempted"] == ["opencli", "soota"]
    assert result.data["provider"] == "soota" and len(calls) == 2


@pytest.mark.parametrize("failure", [AuthBudgetError("429"), ContractError("bad data"), SourceError("unknown")])
def test_access_and_unknown_errors_do_not_switch_providers(settings, monkeypatch, failure):
    calls = stub_process(monkeypatch)

    def fail(*args):
        raise failure

    monkeypatch.setattr(OpenCLIProvider, "inspect", fail)
    with pytest.raises(type(failure)):
        ingest(settings, URL)
    assert not calls


def test_explicit_opencli_does_not_switch_to_soota(settings, monkeypatch):
    calls = stub_process(monkeypatch)
    monkeypatch.setattr(OpenCLIProvider, "inspect", lambda self, source: MediaItem(source=source))

    def fail(*args):
        raise CaptionUnavailable("empty response")

    monkeypatch.setattr(OpenCLIProvider, "get_captions", fail)
    with pytest.raises(CaptionUnavailable):
        ingest(settings, URL, provider="opencli")
    assert not calls


@pytest.mark.parametrize("body", [{}, {"events": []}, {"events": [{"tStartMs": -1, "segs": [{"utf8": "text"}]}]}])
def test_bad_caption_payload_is_not_cached_as_missing(settings, monkeypatch, body):
    stub_process(monkeypatch, body=body)
    provider = SootaProvider(settings)
    item = provider.inspect(recognize(URL))
    with pytest.raises(ContractError):
        provider.get_captions(item)
    assert provider.cache.get_json(item.source, "captions") is None


def test_wrong_video_metadata_rejected(settings, monkeypatch):
    stub_process(monkeypatch, info={**INFO, "id": "OtherID0001"})
    with pytest.raises(ContractError):
        SootaProvider(settings).inspect(recognize(URL))


def test_restrictions_are_sanitized(settings, monkeypatch):
    stub_process(monkeypatch, error="HTTP Error 429 signed-secret-url")
    with pytest.raises(AuthBudgetError) as exc:
        SootaProvider(settings).inspect(recognize(URL))
    assert "secret" not in str(exc.value)


def test_missing_captions_is_partial_and_no_negative_cache(settings, monkeypatch):
    stub_process(monkeypatch, info={**INFO, "subtitles": {}, "automatic_captions": {}})
    result = ingest(settings, URL, provider="soota", max_cost=0)
    assert result.exit_code == 2
    provider = SootaProvider(settings)
    assert provider.cache.get_json(recognize(URL), "captions") is None


def test_language_selection_respects_requested_language_then_official_track():
    tracks = {"official": ["en", "zh-Hans"], "auto": ["zh"]}
    assert select_track(tracks, "zh") == ("zh", TranscriptSource.AUTO)
    assert select_track(tracks, "en") == ("en", TranscriptSource.OFFICIAL)
    assert select_track({"official": ["zh"], "auto": ["zh"]}, "zh") == ("zh", TranscriptSource.OFFICIAL)


def test_unsupported_catalog_and_audio_are_not_silently_paid(settings):
    with pytest.raises(SourceError):
        catalog_provider(recognize("https://www.youtube.com/@Example"), "soota")
    with pytest.raises(SourceError):
        estimate(settings, URL, provider="soota", transcript=TranscriptMode.ASR)
    result = estimate(settings, URL, provider="soota")
    assert result.data["provider"] == "soota" and result.data["estimated_cost_usd"] == 0


def test_metadata_fallback_preserves_previous_records(settings, monkeypatch):
    from soota.models import RequestRecord

    stub_process(monkeypatch)

    def unavailable(self, source):
        self.records.append(RequestRecord(endpoint="opencli:attempt", billed=False))
        raise RuntimeUnavailable("absent")

    monkeypatch.setattr(OpenCLIProvider, "inspect", unavailable)
    item, records, warnings = inspect_item(settings, recognize(URL), max_cost=0)
    assert item.provenance["provider"] == "soota"
    assert [r.endpoint for r in records] == ["opencli:attempt", "soota:youtube/video"]
    assert warnings


def test_feature_output_is_written(settings, monkeypatch, tmp_path):
    from soota.features import call_feature, list_features

    stub_process(monkeypatch)
    target = tmp_path / "detail.json"
    result = call_feature(settings, "youtube.video.detail", params=[f"url={URL}"], provider="soota", output=target)
    assert result.ok and Path(result.data["output"]) == target
    assert json.loads(target.read_text())["metadata"]["title"] == "Example"
    plans = list_features(settings, provider="soota").data["features"]
    assert [r["id"] for r in plans] == ["youtube.video.detail"]


def test_paid_confirmation_still_required_after_both_free_unavailable(settings, monkeypatch):
    from soota.billing import PaymentRequired
    from soota.config import PaymentConfig
    from tests.unit.test_resolver import _youtube_requester

    settings.payment = PaymentConfig(mode="ask")

    def unavailable(*args):
        raise RuntimeUnavailable("unavailable")

    monkeypatch.setattr(OpenCLIProvider, "inspect", unavailable)
    monkeypatch.setattr(SootaProvider, "inspect", unavailable)
    with pytest.raises(PaymentRequired):
        ingest(settings, URL, max_cost=0.1, transcript=TranscriptMode.CAPTIONS_ONLY, requester=_youtube_requester())


def test_counterpart_can_use_soota_and_preserves_original_identity(settings, monkeypatch):
    from soota.counterpart import youtube_counterpart
    from tests.unit.test_content_selection import Client, media

    original = media("bilibili")
    info = {**INFO, "id": media("youtube").source.id}
    stub_process(monkeypatch, info=info)
    fallback = SootaProvider(settings)
    item, captions, _ = youtube_counterpart(Client(missing=True), original, fallback)
    assert captions and captions.language == "zh"
    assert item.provenance["provider"] == "soota"
    assert item.provenance["selection"]["requested_source"]["id"] == original.source.id
    assert item.provenance["youtube_check"]["status"] == "selected"
    assert len(fallback.records) == 2


def test_zero_budget_with_both_free_unavailable_never_constructs_paid_provider(settings, monkeypatch):
    def unavailable(*args):
        raise RuntimeUnavailable("unavailable")

    monkeypatch.setattr(OpenCLIProvider, "inspect", unavailable)
    monkeypatch.setattr(SootaProvider, "inspect", unavailable)
    monkeypatch.setattr("soota.pipeline._provider", lambda *a, **k: pytest.fail("paid provider constructed"))
    with pytest.raises(SourceError):
        ingest(settings, URL, max_cost=0)
