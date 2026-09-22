from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from soota.errors import ContractError
from soota.models import (
    CaptionResult,
    CaptionTrack,
    MediaItem,
    SourceRef,
    TranscriptSource,
    TranscriptStatus,
)
from soota.transcripts.captions import parse_json3, parse_srt

PREFERRED_LANGS = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "en", "en-US", "en-GB")


def unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContractError(
            "TikHub 响应不是 JSON 对象。",
            hint="这是契约漂移，停止把响应写成内容包。",
            details={"type": type(payload).__name__},
        )
    code = payload.get("code", 200)
    if code not in (200, 0, "200", None):
        raise ContractError(
            f"TikHub 业务状态异常: {code}",
            hint=str(payload.get("message") or payload.get("message_zh") or "检查 endpoint 是否仍可用。"),
            details={"code": code},
        )
    data = payload.get("data", payload)
    if (
        isinstance(data, dict)
        and "data" in data
        and set(data.keys()) >= {"data"}
        and not any(key in data for key in ("title", "video_id", "bvid", "captions", "content", "View"))
    ):
        inner = data.get("data")
        if isinstance(inner, dict):
            data = inner
    if not isinstance(data, dict):
        if isinstance(data, str):
            return {"content": data}
        raise ContractError("TikHub data 字段不是对象。", details={"type": type(data).__name__})
    return data


def prefer_language(tracks: list[CaptionTrack], preferred: str | None) -> CaptionTrack | None:
    if not tracks:
        return None

    def rank(track: CaptionTrack) -> tuple[int, int, int]:
        kind_rank = 0 if track.kind == TranscriptSource.OFFICIAL else 1
        langs = [preferred] + list(PREFERRED_LANGS) if preferred else list(PREFERRED_LANGS)
        try:
            lang_rank = next(
                i for i, item in enumerate(langs) if item and track.language.lower().startswith(item.lower())
            )
        except StopIteration:
            lang_rank = 99
        return (kind_rank, lang_rank, 0)

    return sorted(tracks, key=rank)[0]


def _as_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(value, str):
        raw = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def youtube_media(source: SourceRef, payload: Any) -> MediaItem:
    data = unwrap(payload)
    video_id = str(data.get("video_id") or source.id)
    title = data.get("title") or _dig(data, "videoDetails", "title")
    creator = data.get("author") or data.get("channel_name") or _dig(data, "videoDetails", "author")
    duration = _as_int(
        data.get("length_seconds") or data.get("duration_seconds") or _dig(data, "videoDetails", "lengthSeconds")
    )
    published = _as_datetime(data.get("published_at") or data.get("publish_date") or data.get("upload_date"))
    if not title:
        raise ContractError(
            "YouTube 详情缺少 title。",
            hint="检查当前 get_video_info 的最新接口响应；不要在失败后自动降级版本。",
        )
    extras: dict[str, str] = {}
    channel_id = data.get("channel_id")
    if channel_id:
        extras["channel_id"] = str(channel_id)
    caption_count = data.get("caption_count")
    if caption_count is not None:
        extras["caption_count"] = str(caption_count)
    return MediaItem(
        source=source.model_copy(update={"id": video_id, "kind": "video"}),
        title=str(title),
        creator=str(creator) if creator else None,
        published_at=published,
        duration_seconds=duration,
        language=str(data.get("language")) if data.get("language") else None,
        extras=extras,
    )


def youtube_caption_tracks(payload: Any) -> tuple[list[CaptionTrack], dict[str, Any]]:
    data = unwrap(payload)
    if str(data.get("status") or "") in {"processing", "queued", "active"}:
        return [], data
    tracks: list[CaptionTrack] = []
    captions = data.get("captions")
    if isinstance(captions, list):
        for item in captions:
            if not isinstance(item, dict):
                continue
            code = str(item.get("language_code") or item.get("lang") or "").strip()
            if not code:
                continue
            auto = code.startswith("a.") or item.get("kind") in {"asr", "auto"}
            kind = TranscriptSource.AUTO if auto else TranscriptSource.OFFICIAL
            tracks.append(
                CaptionTrack(
                    language=code,
                    name=str(item.get("language_name") or item.get("name") or code),
                    kind=kind,
                )
            )
    return tracks, data


def youtube_caption_content(
    payload: Any,
    *,
    language: str | None,
    source_kind: TranscriptSource,
) -> CaptionResult:
    data = unwrap(payload)
    status = str(data.get("status") or "")
    if status in {"processing", "queued", "active"}:
        return CaptionResult(status=TranscriptStatus.PENDING, language=language, source=source_kind)
    tracks, _ = youtube_caption_tracks(payload)
    if data.get("captions") == [] and not data.get("content"):
        return CaptionResult(status=TranscriptStatus.MISSING, tracks=tracks)
    content = data.get("content")
    fmt = str(data.get("format") or "srt").lower()
    if isinstance(content, str) and content.strip():
        if fmt == "json3" or content.lstrip().startswith("{"):
            segments = parse_json3(content, language=language, source=source_kind)
        else:
            segments = parse_srt(content, language=language, source=source_kind)
        return CaptionResult(
            status=TranscriptStatus.READY,
            source=source_kind,
            language=language,
            tracks=tracks,
            segments=segments,
        )
    if tracks and not content:
        return CaptionResult(status=TranscriptStatus.PENDING, tracks=tracks, language=language)
    raise ContractError(
        "YouTube 字幕响应无法识别为列表或内容。",
        hint="检查 get_video_captions 的 data 字段。",
    )


def bilibili_media(source: SourceRef, payload: Any) -> MediaItem:
    data = unwrap(payload)
    view = data.get("View") if isinstance(data.get("View"), dict) else data
    if not isinstance(view, dict):
        raise ContractError("Bilibili 详情缺少 View/对象。")
    bvid = str(view.get("bvid") or source.id)
    title = view.get("title")
    owner = view.get("owner") if isinstance(view.get("owner"), dict) else {}
    creator = owner.get("name") if owner else view.get("owner_name")
    duration = _as_int(view.get("duration"))
    published = _as_datetime(view.get("pubdate") or view.get("ctime"))
    if not title:
        raise ContractError("Bilibili 详情缺少 title。")
    extras: dict[str, str] = {}
    aid = view.get("aid") or view.get("a_id")
    cid = view.get("cid") or view.get("c_id")
    if aid is not None:
        extras["aid"] = str(aid)
    if cid is not None:
        extras["cid"] = str(cid)
    pages = view.get("pages")
    if isinstance(pages, list) and pages and isinstance(pages[0], dict) and pages[0].get("cid"):
        extras.setdefault("cid", str(pages[0]["cid"]))
    return MediaItem(
        source=source.model_copy(
            update={"id": bvid, "kind": "video", "canonical_url": f"https://www.bilibili.com/video/{bvid}"}
        ),
        title=str(title),
        creator=str(creator) if creator else None,
        published_at=published,
        duration_seconds=duration,
        extras=extras,
    )


def bilibili_caption_tracks(payload: Any) -> list[dict[str, Any]]:
    data = unwrap(payload)
    candidates = [
        data.get("subtitle"),
        _dig(data, "View", "subtitle"),
        data.get("subtitles"),
        data,
    ]
    tracks: list[dict[str, Any]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        items = cand.get("list") or cand.get("subtitles") or cand.get("data")
        if isinstance(items, list):
            tracks.extend(item for item in items if isinstance(item, dict))
    filtered: list[dict[str, Any]] = []
    for item in tracks:
        lan = str(item.get("lan") or item.get("language") or "")
        url = str(item.get("subtitle_url") or item.get("url") or "")
        if "danmaku" in lan.lower() or "danmaku" in str(item.get("lan_doc") or "").lower():
            continue
        if not url:
            continue
        filtered.append(item)
    return filtered


def track_kind_from_bili(item: dict[str, Any]) -> TranscriptSource:
    lan = str(item.get("lan") or "")
    if lan.startswith("ai-") or item.get("type") in (1, "1", "ai"):
        return TranscriptSource.AUTO
    return TranscriptSource.OFFICIAL


def pick_audio_url(payload: Any) -> str:
    data = unwrap(payload)
    streams: list[dict[str, Any]] = []
    for key in ("adaptive_formats", "adaptiveFormats", "dash_audio", "audio"):
        value = data.get(key)
        if isinstance(value, list):
            streams.extend(item for item in value if isinstance(item, dict))
    formats = data.get("formats")
    if isinstance(formats, list):
        streams.extend(item for item in formats if isinstance(item, dict))
    dash = data.get("dash")
    if isinstance(dash, dict) and isinstance(dash.get("audio"), list):
        streams.extend(item for item in dash["audio"] if isinstance(item, dict))
    best: tuple[int, str] | None = None
    for item in streams:
        mime = str(item.get("mime_type") or item.get("mimeType") or item.get("mime") or "").lower()
        url = item.get("url") or item.get("baseUrl") or item.get("base_url")
        if not url:
            continue
        is_audio = (
            "audio" in mime
            or item.get("audioQuality")
            or item.get("audio_quality")
            or "audio" in str(item.get("quality") or "")
        )
        height = _as_int(item.get("height") or item.get("quality_label") or 0) or 0
        if is_audio or (not height and mime.startswith("audio")):
            bitrate = _as_int(item.get("bitrate") or item.get("abr") or item.get("bandwidth") or 0) or 0
            if best is None or bitrate > best[0]:
                best = (bitrate, str(url))
    if best:
        return best[1]
    raise ContractError(
        "响应里没有可下载的音频地址。",
        hint="不要退回去下载完整视频；检查 streams/playurl 字段。",
    )


def _dig(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur
