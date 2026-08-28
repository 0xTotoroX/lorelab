from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse, urlunparse

from soota.errors import InputError, SourceError
from soota.models import SourceRef

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_BV = re.compile(r"BV[0-9A-Za-z]{10}")
_AV = re.compile(r"(?:av|AV)?(\d{1,12})$")
_B23_HOSTS = {"b23.tv", "b23.live", "bili2233.cn"}
_YT_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_BL_HOSTS = {
    "bilibili.com",
    "www.bilibili.com",
    "m.bilibili.com",
    "space.bilibili.com",
    *_B23_HOSTS,
}


def _host(netloc: str) -> str:
    host = netloc.split("@")[-1].split(":")[0].lower()
    if host.startswith("www."):
        return host
    return host


def _clean_url(url: str) -> str:
    raw = url.strip()
    if not raw:
        raise InputError("URL 为空。", hint="请提供 YouTube 或 Bilibili 链接。")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise InputError(f"不支持的 URL scheme: {parsed.scheme}", hint="只接受 http/https 链接。")
    if not parsed.netloc:
        raise InputError("无法解析 URL 主机。", hint="检查链接是否完整。")
    return urlunparse(parsed)


def recognize(url: str) -> SourceRef:
    cleaned = _clean_url(url)
    parsed = urlparse(cleaned)
    host = _host(parsed.netloc)
    path = parsed.path or "/"

    if host in _YT_HOSTS or host.endswith(".youtube.com"):
        return _youtube(cleaned, parsed, host, path)
    if host in _BL_HOSTS or host.endswith(".bilibili.com"):
        return _bilibili(cleaned, parsed, host, path)
    raise SourceError(
        f"暂不支持该平台: {host}",
        hint="MVP 只识别 YouTube 和 Bilibili。其他平台属于后续能力扩展。",
        details={"host": host},
    )


def _youtube(url: str, parsed: object, host: str, path: str) -> SourceRef:
    query = parse_qs(getattr(parsed, "query", "") or "")
    parts = [p for p in path.split("/") if p]

    if host.endswith("youtu.be") and parts:
        video_id = parts[0]
        if _YT_ID.match(video_id):
            return _yt_video(video_id, url)

    if parts[:1] == ["playlist"] or "list" in query and not query.get("v"):
        playlist = (query.get("list") or [None])[0]
        if playlist:
            return SourceRef(
                platform="youtube",
                kind="playlist",
                id=playlist,
                url=url,
                canonical_url=f"https://www.youtube.com/playlist?list={playlist}",
            )

    if parts and parts[0] == "channel" and len(parts) >= 2:
        channel_id = parts[1]
        return SourceRef(
            platform="youtube",
            kind="channel",
            id=channel_id,
            url=url,
            canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        )
    if parts and parts[0].startswith("@") and len(parts[0]) > 1:
        handle = parts[0]
        return SourceRef(
            platform="youtube",
            kind="channel",
            id=handle,
            url=url,
            canonical_url=f"https://www.youtube.com/{handle}",
        )
    if parts and parts[0] in {"c", "user"} and len(parts) >= 2:
        ident = f"{parts[0]}/{parts[1]}"
        return SourceRef(
            platform="youtube",
            kind="channel",
            id=ident,
            url=url,
            canonical_url=f"https://www.youtube.com/{ident}",
        )

    video_id = (query.get("v") or [None])[0]
    if parts[:1] in (["shorts"], ["embed"], ["live"], ["v"]) and len(parts) >= 2:
        video_id = parts[1]
    if video_id and _YT_ID.match(video_id):
        return _yt_video(video_id, url)

    raise SourceError(
        "无法从 YouTube URL 提取稳定 ID。",
        hint="请使用 watch、shorts、youtu.be 或 channel 链接。",
        details={"url": url},
    )


def _yt_video(video_id: str, url: str) -> SourceRef:
    return SourceRef(
        platform="youtube",
        kind="video",
        id=video_id,
        url=url,
        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
    )


def _bilibili(url: str, parsed: object, host: str, path: str) -> SourceRef:
    query = parse_qs(getattr(parsed, "query", "") or "")
    parts = [p for p in path.split("/") if p]

    if host in _B23_HOSTS:
        code = parts[0] if parts else host
        return SourceRef(
            platform="bilibili",
            kind="shortlink",
            id=code,
            url=url,
            canonical_url=url,
        )

    if host.startswith("space.bilibili.com") or (parts and parts[0] == "space"):
        uid = parts[-1] if host.startswith("space.") else (parts[1] if len(parts) > 1 else None)
        if uid and uid.isdigit():
            return SourceRef(
                platform="bilibili",
                kind="user",
                id=uid,
                url=url,
                canonical_url=f"https://space.bilibili.com/{uid}",
            )

    if parts and parts[0] == "video" and len(parts) >= 2:
        token = parts[1].split("?")[0]
        bv = _BV.search(token)
        if bv:
            bvid = bv.group(0)
            return SourceRef(
                platform="bilibili",
                kind="video",
                id=bvid,
                url=url,
                canonical_url=f"https://www.bilibili.com/video/{bvid}",
            )
        av = _AV.match(token)
        if av:
            aid = av.group(1)
            return SourceRef(
                platform="bilibili",
                kind="video",
                id=f"av{aid}",
                url=url,
                canonical_url=f"https://www.bilibili.com/video/av{aid}",
            )

    bvid_q = (query.get("bvid") or [None])[0]
    if bvid_q and _BV.search(bvid_q):
        bvid = _BV.search(bvid_q).group(0)  # type: ignore[union-attr]
        return SourceRef(
            platform="bilibili",
            kind="video",
            id=bvid,
            url=url,
            canonical_url=f"https://www.bilibili.com/video/{bvid}",
        )

    raise SourceError(
        "无法从 Bilibili URL 提取稳定 ID。",
        hint="请使用 /video/BVxxxx、/video/avxxxx 或 space 主页链接。",
        details={"url": url},
    )
