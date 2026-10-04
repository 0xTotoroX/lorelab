from __future__ import annotations

from collections.abc import Callable

from soota.billing import selected_provider
from soota.config import SootaSettings
from soota.errors import InputError
from soota.models import AudioAsset, MediaItem, RequestRecord, SourceRef
from soota.providers.base import AudioProvider
from soota.providers.downie import DownieProvider
from soota.providers.ytdlp import YtDlpProvider


def conditional_audio_estimate(source: SourceRef) -> dict[str, object]:
    from soota.providers.tikhub.client import BILI_ONE_V3, BILI_PLAYURL, YOUTUBE_STREAMS, load_price_snapshot

    endpoints = [YOUTUBE_STREAMS] if source.platform == "youtube" else [BILI_ONE_V3, BILI_PLAYURL]
    prices = load_price_snapshot()["endpoints"]
    known = all(isinstance(prices.get(path), (int, float)) for path in endpoints)
    return {
        "provider": "tikhub",
        "condition": "confirmed_no_captions",
        "endpoints": endpoints,
        "estimated_cost_usd": round(sum(prices[path] for path in endpoints), 6) if known else None,
    }


def selected_audio_provider(settings: SootaSettings, explicit: str | None) -> str:
    name = explicit or settings.audio.provider
    if name not in {"yt-dlp", "downie", "tikhub"}:
        raise InputError("--audio-provider 支持 yt-dlp/downie/tikhub。")
    return name


class ExistingAudioProvider:
    def __init__(self, asset: AudioAsset) -> None:
        self.asset = asset
        self.name = asset.provider or "local"
        self.records: list[RequestRecord] = []

    def get_audio(self, item: MediaItem) -> AudioAsset:
        self.records.append(
            RequestRecord(endpoint="local:shared-audio", billed=False, cache_hit=True, estimated_cost_usd=0)
        )
        return self.asset


def audio_provider(
    settings: SootaSettings, name: str, paid_factory: Callable[[], AudioProvider], *, asset: AudioAsset | None = None
) -> AudioProvider:
    if asset is not None:
        return ExistingAudioProvider(asset)
    selected_provider(settings, name)
    if name == "yt-dlp":
        return YtDlpProvider(settings)
    if name == "downie":
        return DownieProvider(settings)
    if name == "tikhub":
        return paid_factory()
    raise InputError("无效的音频来源。")
