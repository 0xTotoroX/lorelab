from soota.models import SourceRef
from soota.storage.cache import CacheStore


def test_cache_roundtrip_and_redaction(tmp_path) -> None:
    store = CacheStore(tmp_path)
    source = SourceRef(platform="youtube", kind="video", id="dQw4w9WgXcQ", url="u", canonical_url="u")
    store.put_json(source, "raw", {"url": "https://x.com/v?sig=SECRET123", "title": "ok"})
    data = store.get_json(source, "raw")
    assert data is not None
    assert "SECRET123" not in str(data)
    assert store.has(source, "raw")
    assert store.path_for(source, "raw") == store.path_for(source, "raw")
