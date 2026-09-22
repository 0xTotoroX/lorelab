import copy

import pytest

from soota.errors import ContractError
from soota.providers.tikhub.catalog import catalog_params, parse_catalog_page
from soota.routing import recognize
from tests.conftest import load_fixture

CHANNEL = "https://www.youtube.com/channel/UCAAAAAAAAAAAAAAAAAAAAAA"


def test_youtube_catalog_normalizes_documented_fields_without_media_urls() -> None:
    source = recognize(CHANNEL)
    page = parse_catalog_page(source, load_fixture("youtube_catalog.json"), None, 100)
    assert page.title == "Fixture Channel"
    assert page.next_cursor == "fixture-page-2"
    assert [item.duration_seconds for item in page.items] == [1017, 3723]
    assert page.items[0].published_at is None  # Relative dates must not become invented timestamps.
    assert "fixture-secret" not in page.model_dump_json()
    assert "playback_url" not in page.model_dump_json()


def test_youtube_continuation_has_no_channel_metadata() -> None:
    fixture = load_fixture("youtube_catalog.json")
    del fixture["data"]["channel"]
    fixture["data"]["continuation_token"] = None
    page = parse_catalog_page(recognize(CHANNEL), fixture, "fixture-page-2", 100)
    assert page.title is None
    assert page.next_cursor is None
    assert len(page.items) == 2


def test_bilibili_v2_catalog_and_unbounded_page_number() -> None:
    source = recognize("https://space.bilibili.com/178360345/upload/video")
    page = parse_catalog_page(source, load_fixture("bilibili_catalog.json"), None, 1)
    assert page.next_cursor == "2"
    assert page.total_items == 2
    assert page.items[0].source.id == "BV1EXAM00000"
    assert page.items[0].published_at is not None
    params = catalog_params(source, "101", 100, "zh")
    assert params == {"uid": "178360345", "pn": 101, "ps": 100}


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"videos": None},
        {"videos": [], "continuation_token": {}},
        {"videos": [{"title": "missing id"}]},
        {"videos": [{"title": "unsafe id", "video_id": "../../private"}]},
        {"videos": [], "channel": {"id": "different"}},
    ],
)
def test_youtube_catalog_rejects_contract_drift(data) -> None:
    with pytest.raises(ContractError):
        parse_catalog_page(recognize(CHANNEL), {"data": data}, None, 100)


@pytest.mark.parametrize("total", [None, "2", -1, True])
def test_bilibili_catalog_rejects_invalid_totals(total) -> None:
    data = copy.deepcopy(load_fixture("bilibili_catalog.json"))
    data["data"]["page"]["total"] = total
    with pytest.raises(ContractError):
        parse_catalog_page(recognize("https://space.bilibili.com/123"), data, None, 1)


def test_bilibili_empty_page_before_total_is_not_success() -> None:
    with pytest.raises(ContractError):
        parse_catalog_page(
            recognize("https://space.bilibili.com/123"), {"data": {"archives": [], "page": {"total": 100}}}, None, 10
        )
