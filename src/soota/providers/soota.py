from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from soota.config import SootaSettings
from soota.errors import AuthBudgetError, ContractError, SourceError
from soota.models import (
    CapabilitySet,
    CaptionResult,
    MediaItem,
    RequestRecord,
    SourceRef,
    TranscriptSegment,
    TranscriptSource,
    TranscriptStatus,
)
from soota.providers.opencli_runtime import RuntimeUnavailable
from soota.providers.process import run_process
from soota.storage.cache import CacheStore


def capabilities_for(source: SourceRef) -> CapabilitySet:
    supported = source.platform == "youtube" and source.kind == "video"
    return CapabilitySet(inspect=supported, captions=supported)


class SootaProvider:
    """Local acquisition algorithms, starting with yt-dlp YouTube captions."""

    name = "soota"

    def __init__(self, settings: SootaSettings) -> None:
        self.settings = settings
        self.config = settings.local
        scope = hashlib.sha256(
            f"{self.config.binary}|{self.config.cookies_browser}|{settings.default_language}".encode()
        ).hexdigest()[:16]
        self.cache = CacheStore(settings.cache_dir / "soota" / scope)
        self.records: list[RequestRecord] = []

    def _run(self, source: SourceRef, args: list[str], operation: str) -> str:
        binary = shutil.which(self.config.binary)
        if not binary:
            raise RuntimeUnavailable("soota 需要 yt-dlp。", hint="安装 yt-dlp，或通过 SOOTA_YTDLP_BINARY 指定程序。")
        argv = [
            binary,
            "--ignore-config",
            "--no-playlist",
            "--skip-download",
            "--no-progress",
            "--socket-timeout",
            "20",
            "--retries",
            "0",
            "--extractor-retries",
            "0",
        ]
        if self.config.cookies_browser:
            argv += ["--cookies-from-browser", self.config.cookies_browser]
        self.records.append(RequestRecord(endpoint=f"soota:youtube/{operation}", billed=False, estimated_cost_usd=0))
        try:
            result = run_process(
                argv + args + ["--", source.canonical_url],
                timeout=self.config.timeout_seconds,
                max_bytes=self.config.max_output_bytes,
            )
        except FileNotFoundError as exc:
            raise RuntimeUnavailable("yt-dlp 程序已不可用。") from exc
        if result.returncode:
            message = result.stderr.lower()
            if any(
                text in message for text in ("429", "403", "sign in", "login", "cookies", "captcha", "private video")
            ):
                raise AuthBudgetError("yt-dlp 遇到登录、Cookie 或访问限制；请检查浏览器状态，不自动切换付费来源。")
            raise SourceError("yt-dlp 采集失败，未自动重试或切换付费来源。", details={"exit_code": result.returncode})
        return result.stdout

    def _cached(self, source: SourceRef, artifact: str) -> dict[str, Any] | None:
        cached = self.cache.get_json(source, artifact)
        if cached and 0 <= time.time() - cached.get("timestamp", 0) < self.config.cache_seconds:
            self.records.append(
                RequestRecord(endpoint=f"soota:cache:{artifact}", billed=False, cache_hit=True, estimated_cost_usd=0)
            )
            return dict(cached["result"])
        return None

    def inspect(self, source: SourceRef) -> MediaItem:
        if not capabilities_for(source).inspect:
            raise SourceError("soota 当前只接入 YouTube 单视频元数据和字幕。")
        cached = self._cached(source, "inspect")
        if cached:
            item = MediaItem.model_validate(cached)
            if item.source.cache_identity != source.cache_identity:
                raise ContractError("soota 缓存来源不匹配。")
            return item
        raw = self._run(source, ["--dump-single-json"], "video")
        try:
            info = json.loads(raw)
            if not isinstance(info, dict) or info.get("id") != source.id:
                raise ValueError("source mismatch")
            # Store only selected metadata and track names, never signed URLs or headers.
            tracks = {
                kind: [
                    lang
                    for lang, formats in (info.get(key) or {}).items()
                    if lang != "live_chat" and any(f.get("ext") == "json3" for f in formats)
                ]
                for kind, key in (("official", "subtitles"), ("auto", "automatic_captions"))
            }
            item = MediaItem(
                source=source,
                title=info.get("title"),
                creator=info.get("channel") or info.get("uploader"),
                duration_seconds=int(info["duration"]) if info.get("duration") is not None else None,
                language=info.get("language"),
                provenance={"provider": self.name, "engine": "yt-dlp", "caption_tracks": tracks},
            )
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
            raise ContractError("yt-dlp 元数据格式无效或来源不匹配。") from exc
        self.cache.put_json(source, "inspect", {"timestamp": time.time(), "result": item.model_dump(mode="json")})
        return item

    def get_captions(self, item: MediaItem) -> CaptionResult:
        if not capabilities_for(item.source).captions:
            raise SourceError("soota 当前只接入 YouTube 字幕。")
        cached = self._cached(item.source, "captions")
        if cached:
            return CaptionResult.model_validate(cached)
        tracks = item.provenance.get("caption_tracks", {})
        selected = select_track(tracks, self.settings.default_language)
        if selected is None:
            return CaptionResult(status=TranscriptStatus.MISSING)
        language, kind = selected
        with tempfile.TemporaryDirectory(prefix="soota-captions-") as directory:
            self._run(
                item.source,
                [
                    "--write-subs" if kind == TranscriptSource.OFFICIAL else "--no-write-subs",
                    "--write-auto-subs" if kind == TranscriptSource.AUTO else "--no-write-auto-subs",
                    "--sub-langs",
                    re.escape(language),
                    "--sub-format",
                    "json3",
                    "-o",
                    str(Path(directory) / "captions.%(ext)s"),
                ],
                "transcript",
            )
            files = list(Path(directory).glob("captions.*.json3"))
            if len(files) != 1:
                raise SourceError("yt-dlp 未生成所选字幕文件；未把失败缓存为无字幕。")
            if files[0].stat().st_size > self.config.max_output_bytes:
                raise SourceError("yt-dlp 字幕文件超过大小上限。")
            try:
                result = parse_json3(json.loads(files[0].read_text(encoding="utf-8")), language, kind)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
                raise ContractError("yt-dlp 字幕不是有效的 JSON3。") from exc
        self.cache.put_json(
            item.source, "captions", {"timestamp": time.time(), "result": result.model_dump(mode="json")}
        )
        return result


def select_track(tracks: dict[str, Any], preferred: str) -> tuple[str, TranscriptSource] | None:
    candidates = [(lang, TranscriptSource(kind)) for kind in ("official", "auto") for lang in tracks.get(kind, [])]
    if not candidates:
        return None

    def rank(track: tuple[str, TranscriptSource]) -> tuple[int, bool, str]:
        lang, kind = track
        match = 0 if lang == preferred else 1 if lang.split("-")[0] == preferred.split("-")[0] else 2
        return match, kind != TranscriptSource.OFFICIAL, lang

    return min(candidates, key=rank)


def parse_json3(data: dict[str, Any], language: str, kind: TranscriptSource) -> CaptionResult:
    segments: list[TranscriptSegment] = []
    for event in data["events"]:
        text = "".join(part.get("utf8", "") for part in event.get("segs", [])).strip()
        if not text:
            continue
        start = int(event["tStartMs"])
        end = start + int(event.get("dDurationMs", 0))
        if start < 0 or end < start:
            raise ValueError("invalid timestamp")
        segments.append(
            TranscriptSegment(
                segment_id=f"seg-{len(segments) + 1:06d}",
                start_ms=start,
                end_ms=end,
                text=text,
                language=language,
                source=kind,
            )
        )
    if not segments:
        raise ValueError("empty caption body")
    return CaptionResult(status=TranscriptStatus.READY, source=kind, language=language, segments=segments)
