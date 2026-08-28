from soota.models import SourceRef
from soota.providers.tikhub.capability import capabilities_for


def test_video_capabilities() -> None:
    yt = capabilities_for(SourceRef(platform="youtube", kind="video", id="a", url="u", canonical_url="u"))
    assert yt.inspect and yt.captions and yt.audio
    assert not yt.catalog
    ch = capabilities_for(SourceRef(platform="youtube", kind="channel", id="a", url="u", canonical_url="u"))
    assert ch.catalog and not ch.inspect
