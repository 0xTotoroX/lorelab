from soota.errors import AuthBudgetError
from soota.models import TranscriptMode
from soota.pipeline import estimate, ingest


def test_max_cost_is_hard_limit(settings) -> None:
    def requester(method, path, params):  # pragma: no cover
        raise AssertionError("paid call must not happen")

    try:
        ingest(
            settings,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            provider="tikhub",
            transcript=TranscriptMode.AUTO,
            max_cost=0.0001,
            requester=requester,
        )
    except AuthBudgetError as exc:
        assert exc.exit_code == 4
    else:
        raise AssertionError("expected budget error")


def test_http_402_is_auth_budget() -> None:
    from soota.errors import AuthBudgetError
    from soota.providers.tikhub.client import _map_tikhub_error

    class Fake402(Exception):
        status_code = 402

    mapped = _map_tikhub_error(Fake402("402 GET https://api.tikhub.io/x: HTTP 402"))
    assert isinstance(mapped, AuthBudgetError)
    assert mapped.exit_code == 4


def test_estimate_warns_when_paid_balance_short(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        "soota.providers.tikhub.client.TikHubProvider.get_wallet",
        lambda self: {"balance": 0.0, "free_credit": 0.05},
    )
    result = estimate(settings, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result.ok is True
    wallet = result.data["wallet"]
    assert wallet["sufficient"] is False
    assert wallet["paid_required_usd"] > 0
    assert any("余额不足" in warning for warning in result.warnings)


def test_ingest_stops_before_paid_call_when_wallet_short(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        "soota.providers.tikhub.client.TikHubProvider.get_wallet",
        lambda self: {"balance": 0.0, "free_credit": 0.05},
    )

    def requester(method, path, params):  # pragma: no cover
        raise AssertionError("paid call must not happen")

    try:
        ingest(
            settings,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            provider="tikhub",
            transcript=TranscriptMode.AUTO,
            requester=requester,
        )
    except AuthBudgetError as exc:
        assert exc.exit_code == 4
        assert "付费余额不足" in exc.message
    else:
        raise AssertionError("expected wallet error")


def test_bilibili_info_can_use_free_credit(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        "soota.providers.tikhub.client.TikHubProvider.get_wallet",
        lambda self: {"balance": 0.0, "free_credit": 0.05},
    )
    result = estimate(
        settings,
        "https://www.bilibili.com/video/BV1M1421t7hT",
        provider="tikhub",
        transcript=TranscriptMode.NONE,
    )
    wallet = result.data["wallet"]
    assert wallet["paid_required_usd"] == 0
    assert wallet["sufficient"] is True


def test_estimate_keeps_latest_api_audio_when_ytdlp_present(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        "soota.providers.tikhub.client.TikHubProvider.get_wallet",
        lambda self: {"balance": 5.0, "free_credit": 2.0},
    )
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/bin/yt-dlp" if name == "yt-dlp" else None,
    )
    result = estimate(settings, "https://www.bilibili.com/video/BV1M1421t7hT")
    endpoints = result.data["endpoints"]
    assert "/api/v1/bilibili/web/fetch_one_video_v3" in endpoints
    assert "/api/v1/bilibili/web/fetch_video_playurl" in endpoints


def test_estimate_keeps_audio_when_ytdlp_missing(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        "soota.providers.tikhub.client.TikHubProvider.get_wallet",
        lambda self: {"balance": 5.0, "free_credit": 2.0},
    )
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = estimate(settings, "https://www.bilibili.com/video/BV1EXAM00000")
    assert any("playurl" in e for e in result.data["endpoints"])
