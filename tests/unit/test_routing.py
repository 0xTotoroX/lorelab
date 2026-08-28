from soota.errors import SourceError
from soota.routing import recognize


def test_youtube_watch() -> None:
    ref = recognize("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert ref.platform == "youtube"
    assert ref.kind == "video"
    assert ref.id == "dQw4w9WgXcQ"
    assert ref.canonical_url.endswith("dQw4w9WgXcQ")


def test_youtube_short_and_embed() -> None:
    assert recognize("https://youtu.be/dQw4w9WgXcQ").id == "dQw4w9WgXcQ"
    assert recognize("https://www.youtube.com/shorts/dQw4w9WgXcQ").id == "dQw4w9WgXcQ"
    assert recognize("https://www.youtube.com/embed/dQw4w9WgXcQ").kind == "video"


def test_youtube_channel_and_playlist() -> None:
    channel = recognize("https://www.youtube.com/@RickAstley")
    assert channel.kind == "channel"
    playlist = recognize("https://www.youtube.com/playlist?list=PLtest123")
    assert playlist.kind == "playlist"
    mixed = recognize("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLtest123")
    assert mixed.kind == "video"


def test_bilibili_bv_and_av() -> None:
    bv = recognize("https://www.bilibili.com/video/BV1M1421t7hT")
    assert bv.platform == "bilibili" and bv.id == "BV1M1421t7hT"
    av = recognize("https://www.bilibili.com/video/av123456")
    assert av.id == "av123456"
    short = recognize("https://b23.tv/1ZuB5NC")
    assert short.kind == "shortlink"


def test_unknown_host() -> None:
    try:
        recognize("https://example.com/video/1")
    except SourceError as exc:
        assert exc.exit_code == 5
    else:
        raise AssertionError("expected SourceError")
