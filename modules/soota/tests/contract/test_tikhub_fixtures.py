from soota.errors import ContractError
from soota.models import SourceRef, TranscriptSource
from soota.providers.tikhub.normalize import (
    pick_audio_url,
    youtube_caption_content,
    youtube_media,
)
from soota.secrets import redact_any
from soota.transcripts.conversion import convert_captions
from tests.conftest import load_fixture


def test_youtube_info_contract() -> None:
    source = SourceRef(platform="youtube", kind="video", id="dQw4w9WgXcQ", url="u", canonical_url="u")
    item = youtube_media(source, load_fixture("youtube_info.json"))
    assert item.title == "Never Gonna Give You Up"


def test_youtube_caption_and_missing() -> None:
    ready = youtube_caption_content(
        load_fixture("youtube_captions_srt.json"),
        language="en",
        source_kind=TranscriptSource.OFFICIAL,
    )
    assert convert_captions(ready).segments[0].text.startswith("Never")
    missing = youtube_caption_content(
        load_fixture("youtube_captions_missing.json"),
        language=None,
        source_kind=TranscriptSource.OFFICIAL,
    )
    assert missing.status.value == "missing"


def test_drift_raises() -> None:
    source = SourceRef(platform="youtube", kind="video", id="x", url="u", canonical_url="u")
    try:
        youtube_media(source, load_fixture("drift.json"))
    except ContractError as exc:
        assert exc.exit_code == 8
    else:
        raise AssertionError("expected drift")


def test_signed_url_redacted_from_fixture() -> None:
    payload = load_fixture("youtube_streams.json")
    url = pick_audio_url(payload)
    assert "sig=" in url
    redacted = redact_any(payload)
    assert "SUPERSECRET" not in str(redacted)
