from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx

from soota import TIKHUB_SDK_VERSION
from soota.errors import AuthBudgetError, ContractError, SourceError, TranscriptError
from soota.models import (
    AudioAsset,
    CapabilitySet,
    CaptionResult,
    CaptionTrack,
    MediaItem,
    RequestRecord,
    SourceRef,
    TranscriptSource,
    TranscriptStatus,
)
from soota.providers.tikhub.capability import capabilities_for
from soota.providers.tikhub.normalize import (
    bilibili_caption_tracks,
    bilibili_media,
    pick_audio_url,
    prefer_language,
    track_kind_from_bili,
    unwrap,
    youtube_caption_content,
    youtube_caption_tracks,
    youtube_media,
)
from soota.secrets import load_tikhub_api_key, redact_url
from soota.storage.cache import CacheStore
from soota.transcripts.captions import parse_bilibili_body
from soota.transcripts.download import fetch_audio_ytdlp

YOUTUBE_INFO = "/api/v1/youtube/web_v2/get_video_info_v2"
YOUTUBE_CAPTIONS = "/api/v1/youtube/web_v2/get_video_captions"
YOUTUBE_CAPTIONS_RESULT = "/api/v1/youtube/web_v2/get_video_captions_result"
YOUTUBE_STREAMS = "/api/v1/youtube/web_v2/get_video_streams_v2"
BILI_ONE = "/api/v1/bilibili/web/fetch_one_video"
BILI_ONE_V3 = "/api/v1/bilibili/web/fetch_one_video_v3"
BILI_SUBTITLE = "/api/v1/bilibili/web/fetch_video_subtitle"
BILI_PLAYURL = "/api/v1/bilibili/web/fetch_video_playurl"

SNAPSHOT_PATH = Path(__file__).with_name("price_snapshot.json")


def load_price_snapshot() -> dict[str, Any]:
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ContractError("价格快照不是对象。")
    return cast(dict[str, Any], payload)


class TikHubProvider:
    name = "tikhub"

    def __init__(
        self,
        *,
        cache: CacheStore,
        api_key: str | None = None,
        base_url: str = "https://api.tikhub.io",
        timeout: float = 60.0,
        requester: Callable[..., Any] | None = None,
        http_get: Callable[[str], httpx.Response] | None = None,
        preferred_language: str = "zh",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache = cache
        self.api_key = api_key if api_key is not None else load_tikhub_api_key()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.preferred_language = preferred_language
        self._requester = requester
        self._http_get = http_get
        self._client: Any = None
        self._sleep = sleep
        self.records: list[RequestRecord] = []
        self.snapshot = load_price_snapshot()

    def recognize(self, url: str) -> SourceRef | None:
        from soota.routing import recognize

        try:
            source = recognize(url)
        except (SourceError, Exception):
            return None
        if source.platform in {"youtube", "bilibili"}:
            return source
        return None

    def capabilities(self, source: SourceRef) -> CapabilitySet:
        return capabilities_for(source)

    def estimate_requests(self, source: SourceRef, *, need_captions: bool, need_audio: bool) -> list[str]:
        caps = self.capabilities(source)
        endpoints: list[str] = []
        local_audio = shutil.which("yt-dlp") is not None
        if source.platform == "youtube" and source.kind == "video":
            endpoints.append(YOUTUBE_INFO)
            if need_captions and caps.captions:
                endpoints.extend([YOUTUBE_CAPTIONS, YOUTUBE_CAPTIONS])
            if need_audio and caps.audio and not local_audio:
                endpoints.append(YOUTUBE_STREAMS)
        elif source.platform == "bilibili" and source.kind in {"video", "shortlink"}:
            endpoints.append(BILI_ONE if source.kind == "video" and source.id.startswith("BV") else BILI_ONE_V3)
            if need_captions and caps.captions:
                endpoints.append(BILI_SUBTITLE)
            if need_audio and caps.audio and not local_audio:
                endpoints.append(BILI_PLAYURL)
        return endpoints

    def estimate_cost(self, endpoints: list[str]) -> tuple[float | None, str]:
        prices = self.snapshot.get("endpoints", {})
        total = 0.0
        known = True
        for path in endpoints:
            price = prices.get(path)
            if price is None:
                known = False
            else:
                total += float(price)
        basis = f"snapshot:{self.snapshot.get('as_of')}"
        if not endpoints:
            return (0.0, basis)
        return (total if known else None, basis)

    def get_wallet(self) -> dict[str, float] | None:
        if not self.api_key:
            return None
        if self._requester is not None:
            return None
        payload = self._sdk().tikhub_user.get_user_info()
        user = payload.get("user_data") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            raise ContractError("TikHub 用户信息缺少 user_data。")
        return {
            "balance": float(user.get("balance") or 0),
            "free_credit": float(user.get("free_credit") or 0),
        }

    def assess_wallet(self, endpoints: list[str], wallet: dict[str, float]) -> dict[str, Any]:
        prices = self.snapshot.get("endpoints", {})
        free_map = self.snapshot.get("allow_free_credit", {})
        paid_required = 0.0
        freeable_required = 0.0
        unknown = False
        for path in endpoints:
            price = prices.get(path) if isinstance(prices, dict) else None
            if price is None:
                unknown = True
                continue
            amount = float(price)
            allows_free = bool(free_map.get(path, False)) if isinstance(free_map, dict) else False
            if allows_free:
                freeable_required += amount
            else:
                paid_required += amount
        balance = float(wallet.get("balance") or 0)
        free_credit = float(wallet.get("free_credit") or 0)
        shortfall_paid = max(0.0, round(paid_required - balance, 6))
        remaining_paid = max(0.0, balance - paid_required)
        shortfall_freeable = max(0.0, round(freeable_required - remaining_paid - free_credit, 6))
        shortfall = round(shortfall_paid + shortfall_freeable, 6)
        sufficient: bool | None
        if unknown:
            sufficient = None
        else:
            sufficient = shortfall == 0.0
        return {
            "balance": balance,
            "free_credit": free_credit,
            "paid_required_usd": round(paid_required, 6),
            "freeable_required_usd": round(freeable_required, 6),
            "shortfall_usd": None if unknown else shortfall,
            "sufficient": sufficient,
        }

    def inspect(self, source: SourceRef) -> MediaItem:
        cached = self.cache.get_json(source, "inspect")
        if cached:
            self.records.append(RequestRecord(endpoint="cache:inspect", billed=False, cache_hit=True))
            return MediaItem.model_validate(cached["item"])
        payload = self._inspect_payload(source)
        item = youtube_media(source, payload) if source.platform == "youtube" else bilibili_media(source, payload)
        self.cache.put_json(source, "inspect", {"item": item.model_dump(mode="json"), "raw": payload})
        if item.source.id != source.id:
            self.cache.put_json(item.source, "inspect", {"item": item.model_dump(mode="json"), "raw": payload})
        return item

    def get_captions(self, item: MediaItem) -> CaptionResult:
        cached = self.cache.get_json(item.source, "captions")
        if cached:
            self.records.append(RequestRecord(endpoint="cache:captions", billed=False, cache_hit=True))
            return CaptionResult.model_validate(cached)
        if item.source.platform == "youtube":
            result = self._youtube_captions(item)
        else:
            result = self._bilibili_captions(item)
        self.cache.put_json(item.source, "captions", result.model_dump(mode="json"))
        return result

    def get_audio(self, item: MediaItem) -> AudioAsset:
        dest = self.cache.audio_path(item.source)
        if dest.is_file() and dest.stat().st_size > 0:
            self.records.append(RequestRecord(endpoint="cache:audio", billed=False, cache_hit=True))
            return AudioAsset(path=dest)
        if self._requester is None and shutil.which("yt-dlp"):
            try:
                fetch_audio_ytdlp(item.source.canonical_url, dest)
                if dest.is_file() and dest.stat().st_size > 0:
                    self.records.append(RequestRecord(endpoint="local:yt-dlp", billed=False, note="local-audio-first"))
                    return AudioAsset(path=dest)
            except Exception:
                pass
        try:
            cached = self.cache.get_json(item.source, "streams")
            if cached:
                self.records.append(RequestRecord(endpoint="cache:streams", billed=False, cache_hit=True))
                payload = cached.get("raw")
            else:
                payload = self._audio_payload(item)
                self.cache.put_json(item.source, "streams", {"raw": payload}, redact=False)
            url = pick_audio_url(payload)
            self._download(url, dest)
            if dest.is_file() and dest.stat().st_size > 0:
                return AudioAsset(path=dest)
            raise TranscriptError("音频下载结果为空。")
        except AuthBudgetError:
            raise
        except Exception as exc:
            self.records.append(RequestRecord(endpoint="local:yt-dlp", billed=False, note="tikhub-audio-fallback"))
            try:
                fetch_audio_ytdlp(item.source.canonical_url, dest)
            except Exception as fallback_exc:
                raise TranscriptError(
                    "TikHub 音频失败，yt-dlp 回退也失败。",
                    hint=str(fallback_exc),
                ) from exc
            return AudioAsset(path=dest)

    def _inspect_payload(self, source: SourceRef) -> Any:
        if source.platform == "youtube":
            return self._call(YOUTUBE_INFO, {"video_id": source.id, "need_format": True}, billed=True)
        if source.kind == "shortlink" or source.id.startswith("av"):
            return self._call(BILI_ONE_V3, {"url": source.canonical_url or source.url}, billed=True)
        return self._call(BILI_ONE, {"bv_id": source.id}, billed=True)

    def _youtube_captions(self, item: MediaItem) -> CaptionResult:
        listed = self._call(
            YOUTUBE_CAPTIONS,
            {"video_id": item.source.id, "format": "srt"},
            billed=True,
        )
        listed = self._await_captions(listed, item.source.id)
        tracks, data = youtube_caption_tracks(listed)
        content = youtube_caption_content(listed, language=None, source_kind=TranscriptSource.OFFICIAL)
        if content.status == TranscriptStatus.READY:
            return content
        if content.status == TranscriptStatus.MISSING and not tracks:
            return content
        track = prefer_language(tracks or content.tracks, self.preferred_language)
        if track is None:
            return CaptionResult(status=TranscriptStatus.MISSING, tracks=tracks)
        fetched = self._call(
            YOUTUBE_CAPTIONS,
            {
                "video_id": item.source.id,
                "language_code": track.language,
                "format": "srt",
            },
            billed=True,
        )
        fetched = self._await_captions(fetched, item.source.id)
        return youtube_caption_content(fetched, language=track.language, source_kind=track.kind)

    def _await_captions(self, payload: Any, video_id: str) -> Any:
        data = unwrap(payload) if isinstance(payload, dict) else {}
        job_id = str(data.get("job_id") or "")
        status = str(data.get("status") or "")
        if not job_id or status not in {"processing", "queued", "active"}:
            return payload
        for _ in range(20):
            self._sleep(3)
            result = self._call(
                YOUTUBE_CAPTIONS_RESULT,
                {"job_id": job_id, "format": "srt"},
                billed=False,
            )
            inner = unwrap(result)
            inner_status = str(inner.get("status") or "")
            if inner_status == "completed" or inner.get("content"):
                return result
            if inner_status in {"failed", "error"}:
                raise TranscriptError("YouTube 字幕异步任务失败。", hint="稍后重试同一视频，不要换 endpoint 死磕。")
        raise TranscriptError("YouTube 字幕异步任务超时。", hint="可稍后再 ingest；result 接口不计费。")

    def _bilibili_captions(self, item: MediaItem) -> CaptionResult:
        inspect_cached = self.cache.get_json(item.source, "inspect") or {}
        inspect_raw = inspect_cached.get("raw") if isinstance(inspect_cached, dict) else None
        tracks_raw = bilibili_caption_tracks(inspect_raw) if inspect_raw is not None else []
        if not tracks_raw:
            aid = item.extras.get("aid")
            cid = item.extras.get("cid")
            if aid and cid:
                payload = self._call(BILI_SUBTITLE, {"a_id": aid, "c_id": cid}, billed=True)
                tracks_raw = bilibili_caption_tracks(payload)
            elif inspect_raw is None:
                payload = self._inspect_payload(item.source)
                tracks_raw = bilibili_caption_tracks(payload)
        if not tracks_raw:
            return CaptionResult(status=TranscriptStatus.MISSING)
        official = [t for t in tracks_raw if track_kind_from_bili(t) == TranscriptSource.OFFICIAL]
        chosen = (official or tracks_raw)[0]
        kind = track_kind_from_bili(chosen)
        language = str(chosen.get("lan") or self.preferred_language)
        url = str(chosen.get("subtitle_url") or chosen.get("url"))
        if url.startswith("//"):
            url = "https:" + url
        body = self._get_json(url)
        self.records.append(RequestRecord(endpoint="cdn:bilibili-subtitle", billed=False, note=redact_url(url)))
        segments = parse_bilibili_body(body, language=language, source=kind)
        if not segments:
            return CaptionResult(status=TranscriptStatus.MISSING, language=language)
        return CaptionResult(
            status=TranscriptStatus.READY,
            source=kind,
            language=language,
            tracks=[CaptionTrack(language=language, kind=kind)],
            segments=segments,
        )

    def _audio_payload(self, item: MediaItem) -> Any:
        if item.source.platform == "youtube":
            return self._call(YOUTUBE_STREAMS, {"video_id": item.source.id}, billed=True)
        cid = item.extras.get("cid")
        if not cid:
            raise TranscriptError("Bilibili 音频缺少 cid。", hint="先 inspect 成功后再拉音频。")
        return self._call(BILI_PLAYURL, {"bv_id": item.source.id, "cid": cid}, billed=True)

    def _call(self, path: str, params: dict[str, Any], *, billed: bool) -> Any:
        prices = self.snapshot.get("endpoints", {})
        cost = prices.get(path)
        self.records.append(
            RequestRecord(
                endpoint=path,
                billed=billed,
                cache_hit=False,
                estimated_cost_usd=float(cost) if cost is not None else None,
            )
        )
        if self._requester is not None:
            return self._requester("GET", path, params)
        client = self._sdk()
        try:
            return client._request("GET", path, params=params)
        except Exception as exc:
            raise _map_tikhub_error(exc) from exc

    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise AuthBudgetError(
                "未找到 TikHub API Key。",
                hint="export TIKHUB_API_KEY 或 Keychain service=soota.tikhub account=api_key。不要把 Key 发给聊天。",
            )
        from tikhub import TikHub

        self._client = TikHub(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, max_retries=2)
        if getattr(self._client, "__version__", None) not in {None, TIKHUB_SDK_VERSION}:
            pass
        return self._client

    def _get_json(self, url: str) -> Any:
        if self._http_get is not None:
            response = self._http_get(url)
            return response.json()
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def _download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        if self._http_get is not None:
            response = self._http_get(url)
            tmp.write_bytes(response.content)
            tmp.replace(dest)
            self.records.append(RequestRecord(endpoint="cdn:audio", billed=False, note=redact_url(url)))
            return
        timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        tmp.replace(dest)
        self.records.append(RequestRecord(endpoint="cdn:audio", billed=False, note=redact_url(url)))


def _map_tikhub_error(exc: Exception) -> Exception:
    name = type(exc).__name__
    message = str(exc)
    status = getattr(exc, "status_code", None)
    if status == 402 or " HTTP 402" in message or message.startswith("402 "):
        return AuthBudgetError(
            "TikHub 余额不足（HTTP 402）。",
            hint="到 user.tikhub.io 充值后再 ingest 一次。不要重复重试失败的计费接口。",
        )
    if name in {"TikHubAuthError", "TikHubConfigError"}:
        return AuthBudgetError("TikHub 鉴权失败。", hint="检查 TIKHUB_API_KEY 是否有效，且不要把 Key 写入配置文件。")
    if name in {"TikHubPermissionError"}:
        return AuthBudgetError("TikHub 拒绝该请求。", hint="可能是余额不足或权限不足，先在控制台查看额度。")
    if name in {"TikHubRateLimitError"}:
        return SourceError("TikHub 限流。", hint="降低并发，稍后重试同一来源。")
    if name in {"TikHubNotFoundError"}:
        return SourceError("来源不存在或 endpoint 已移除。", hint=message)
    if name in {"TikHubValidationError"}:
        return ContractError("TikHub 响应无法解析。", hint=message)
    if name.startswith("TikHub"):
        return SourceError(f"TikHub 调用失败: {message}", hint="查看 ledger 中的 endpoint，不要无上限重试计费接口。")
    return SourceError(message)
