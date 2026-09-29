from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from soota.errors import CaptionUnavailable, SourceError
from soota.models import CaptionResult, MediaItem, TranscriptStatus
from soota.providers.opencli import OpenCLIProvider
from soota.providers.opencli_runtime import RuntimeUnavailable
from soota.providers.ytdlp import YtDlpProvider
from soota.routing import recognize


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def creator_name(item: MediaItem) -> str:
    return re.sub(r"\s*\(mid:\s*\d+\)\s*$", "", item.creator or "").strip()


def links(text: str) -> list[str]:
    return re.findall(r'https?://[^\s<>"\u3000，。；）)]+', text)


def title_score(left: str, right: str, creator: str) -> float:
    a, b = normalized(left).replace(normalized(creator), ""), normalized(right).replace(normalized(creator), "")
    if min(len(a), len(b)) < 8:
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b)) * 0.2 + 0.8
    return SequenceMatcher(None, a, b).ratio()


def same_episode(original: MediaItem, candidate: MediaItem) -> bool:
    name = creator_name(original)
    left, right = [(title or "").replace(name, "") for title in (original.title, candidate.title)]
    numbers = [{int(n) for n in re.findall(r"\d+", unicodedata.normalize("NFKC", title))} for title in (left, right)]
    episodes = [set(re.findall(r"第([零〇一二三四五六七八九十百两\d]+)[集期章节季]", title)) for title in (left, right)]
    if numbers[0] and numbers[1] and numbers[0] != numbers[1]:
        return False
    if episodes[0] and episodes[1] and episodes[0] != episodes[1]:
        return False
    if title_score(original.title or "", candidate.title or "", creator_name(original)) < 0.8:
        return False
    if not original.duration_seconds or not candidate.duration_seconds:
        return False
    if abs(original.duration_seconds - candidate.duration_seconds) > max(120, original.duration_seconds * 0.2):
        return False
    if not original.published_at or not candidate.published_at:
        return False
    return abs((original.published_at.date() - candidate.published_at.date()).days) <= 14


def author_evidence(original: MediaItem, channel: dict[str, str], video: MediaItem) -> list[str]:
    """Names discover candidates; exact cross-links establish an identity relation."""
    channel_id = channel.get("channelId")
    if not channel_id or video.extras.get("channelId") != channel_id:
        return []
    evidence: list[str] = []
    for url in links(original.extras.get("description", "")):
        try:
            source = recognize(url)
        except SourceError:
            continue
        if source.platform != "youtube":
            continue
        identities = {channel_id, channel.get("handle", ""), channel.get("handle", "").lstrip("@")}
        if (
            source.kind == "video"
            and source.id == video.source.id
            or source.kind == "channel"
            and source.id in identities
        ):
            evidence.append("bilibili_description_links_youtube")
    mid = re.search(r"\(mid:\s*(\d+)\)", original.creator or "")
    for url in links(channel.get("description", "") + "\n" + video.extras.get("description", "")):
        parsed = urlparse(url)
        if parsed.hostname not in {"space.bilibili.com", "www.bilibili.com", "bilibili.com"}:
            continue
        if parsed.hostname == "space.bilibili.com" and mid and parsed.path.strip("/") == mid[1]:
            evidence.append("youtube_description_links_bilibili_creator")
        if parsed.path.rstrip("/") == f"/video/{original.source.id}":
            evidence.append("youtube_description_links_bilibili_video")
    return sorted(set(evidence))


def channel_fields(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {row["field"]: str(row["value"]) for row in rows if isinstance(row.get("field"), str) and "value" in row}


def _youtube_counterpart(
    client: OpenCLIProvider, original: MediaItem, caption_fallback: YtDlpProvider | None = None
) -> tuple[MediaItem, CaptionResult | None, list[str]]:
    name = creator_name(original)
    report: dict[str, Any] = {"status": "not_found", "candidates": []}
    original.provenance["youtube_check"] = report
    if not name:
        return original, None, ["缺少博主名称，未搜索 YouTube。"]
    report["stage"] = "channel_search"
    channels = client._run("youtube", "search", [name, "--type", "channel", "--limit", "5"])
    exact = {str(r.get("url")) for r in channels[:5] if normalized(str(r.get("title", ""))) == normalized(name)}
    if len(exact) != 1:
        report["status"] = "ambiguous" if exact else "no_same_name_channel"
        return original, None, ["未找到唯一同名 YouTube 频道，保留 B站来源。"]
    channel_url = next(iter(exact))
    channel_source = recognize(channel_url)
    if channel_source.platform != "youtube" or channel_source.kind != "channel":
        raise SourceError("YouTube 频道搜索返回了无效链接。")
    report["stage"] = "channel_metadata"
    channel = channel_fields(client._run("youtube", "channel", [channel_source.id, "--limit", "1"]))
    if not channel.get("channelId") or normalized(channel.get("name", "")) != normalized(name):
        report["status"] = "channel_name_mismatch"
        return original, None, ["YouTube 频道元数据与搜索名称不一致，保留 B站来源。"]
    report["stage"] = "video_search"
    rows = client._run("youtube", "search", [f"{name} {original.title or ''}", "--type", "video", "--limit", "5"])
    matches: list[MediaItem] = []
    seen: set[str] = set()
    for row in rows[:5]:
        if normalized(str(row.get("channel", ""))) != normalized(name):
            continue
        if title_score(original.title or "", str(row.get("title", "")), name) < 0.8:
            continue
        source = recognize(str(row.get("url", "")))
        if source.platform != "youtube" or source.kind != "video" or source.id in seen:
            continue
        seen.add(source.id)
        report["stage"] = "video_metadata"
        candidate = client.inspect(source)
        if not same_episode(original, candidate):
            continue
        if candidate.extras.get("channelId") != channel.get("channelId"):
            continue
        evidence = author_evidence(original, channel, candidate)
        report["candidates"].append(
            {"url": source.canonical_url, "author_confirmed": "bilibili_description_links_youtube" in evidence}
        )
        candidate.provenance["selection"] = {
            "requested_source": original.source.model_dump(mode="json"),
            "channel_id": channel.get("channelId"),
            "evidence": evidence + ["same_name", "channel_id_match", "title_duration_date_match"],
            "author_crosslink_confirmed": "bilibili_description_links_youtube" in evidence,
        }
        matches.append(candidate)
    if len(matches) != 1:
        report["status"] = "needs_review" if report["candidates"] else "no_matching_episode"
        return original, None, ["YouTube 同名频道的同期视频未唯一匹配，保留 B站；候选与原因已记录。"]
    chosen = matches[0]
    report["stage"] = "youtube_captions"
    try:
        captions = client.get_captions(chosen)
    except (CaptionUnavailable, RuntimeUnavailable):
        if caption_fallback is None:
            raise
        captions = CaptionResult(status=TranscriptStatus.MISSING)
    if captions.status != TranscriptStatus.READY and caption_fallback is not None:
        local_item = caption_fallback.inspect(chosen.source)
        captions = caption_fallback.get_captions(local_item)
        if captions.status == TranscriptStatus.READY:
            local_item.provenance["selection"] = chosen.provenance["selection"]
            chosen = local_item
    if captions.status != TranscriptStatus.READY or not captions.segments:
        report["status"] = "youtube_captions_missing"
        return original, None, ["已找到同一期 YouTube 视频，但没有可用字幕，保留 B站来源。"]
    chosen.provenance["youtube_check"] = {**report, "status": "selected"}
    return chosen, captions, ["已匹配唯一同名频道与同一期视频，采用 YouTube 字幕和时间轴；匹配依据已记录。"]


def youtube_counterpart(
    client: OpenCLIProvider, original: MediaItem, caption_fallback: YtDlpProvider | None = None
) -> tuple[MediaItem, CaptionResult | None, list[str]]:
    try:
        return _youtube_counterpart(client, original, caption_fallback)
    except SourceError as exc:
        original.provenance["youtube_check"] = {
            **original.provenance.get("youtube_check", {}),
            "status": "failed",
            "error_code": exc.code,
        }
        return (
            original,
            None,
            ["YouTube 可选检查失败，未重试该请求；继续获取输入的 B站字幕，不能据此判断没有同名频道。"],
        )
