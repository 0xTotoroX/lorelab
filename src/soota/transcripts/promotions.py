from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import httpx

from soota.errors import InputError
from soota.models import MediaItem, TranscriptDocument, TranscriptStatus

CATEGORIES = {"sponsor", "selfpromo"}
ATTRIBUTION = "SponsorBlock contributors (CC BY-NC-SA 4.0), https://sponsor.ajay.app/"


def parse_ranges(values: list[str]) -> list[tuple[float, float]]:
    ranges = []
    for value in values:
        try:
            start, end = map(float, value.split(":"))
        except (ValueError, TypeError) as exc:
            raise InputError("--exclude-range 使用 起秒:止秒，例如 12.5:35。") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise InputError("排除区间必须是有限非负秒数，结束时间大于开始时间。")
        ranges.append((start, end))
    return ranges


def sponsor_ranges(item: MediaItem) -> tuple[list[tuple[float, float]], str]:
    prefix = hashlib.sha256(item.source.id.encode()).hexdigest()[:4]
    try:
        response = httpx.get(
            f"https://sponsor.ajay.app/api/skipSegments/{prefix}",
            params={"service": "YouTube", "categories": json.dumps(sorted(CATEGORIES)), "actionTypes": '["skip"]'},
            timeout=10,
        )
        if response.status_code == 404:
            return [], "no_annotations"
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError
        ranges: list[tuple[float, float]] = []
        for video in data:
            if video.get("videoID") != item.source.id:
                continue
            for entry in video.get("segments", []):
                if entry.get("category") not in CATEGORIES or entry.get("actionType", "skip") != "skip":
                    continue
                start, end = entry["segment"]
                if any(
                    isinstance(n, bool) or not isinstance(n, (float, int)) or not math.isfinite(n) for n in [start, end]
                ):
                    raise ValueError
                if start < 0 or end <= start:
                    raise ValueError
                duration = entry.get("videoDuration", 0)
                if item.duration_seconds:
                    if end > item.duration_seconds + 1 or duration and abs(duration - item.duration_seconds) > 2:
                        return [], "duration_mismatch"
                ranges.append((float(start), float(end)))
        return ranges, "annotated" if ranges else "no_annotations"
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
        return [], "unavailable"


def filter_promotions(
    item: MediaItem, document: TranscriptDocument, *, automatic: bool, ranges: list[tuple[float, float]]
) -> tuple[TranscriptDocument, dict[str, Any], list[str]]:
    selected = list(ranges)
    state = "manual_ranges" if selected else "disabled"
    if automatic and item.source.platform != "youtube":
        state = "manual_ranges" if selected else "unsupported_platform"
    if automatic and item.source.platform == "youtube":
        community, state = sponsor_ranges(item)
        selected += community
    report: dict[str, Any] = {
        "status": state,
        "ranges_seconds": [list(interval) for interval in selected],
        "removed_segment_ids": [],
        "review_required": automatic,
    }
    if automatic and item.source.platform == "youtube":
        report["attribution"] = ATTRIBUTION
    kept = []
    for segment in document.segments:
        if segment.start_ms is None or segment.end_ms is None:
            if selected:
                raise InputError("字幕没有完整时间轴，不能按时间范围过滤。")
            kept.append(segment)
            continue
        if any(segment.start_ms < end * 1000 and segment.end_ms > start * 1000 for start, end in selected):
            report["removed_segment_ids"].append(segment.segment_id)
        else:
            kept.append(segment)
    report["boundary_policy"] = "remove_overlapping_cues_preserve_timestamps_and_ids"
    warnings = []
    if automatic:
        warnings.append("推广过滤仅覆盖已有标注，未标注片段仍需 Agent 复核；无标注不代表没有推广。")
    if report["removed_segment_ids"]:
        warnings.append(f"已排除 {len(report['removed_segment_ids'])} 段推广相关字幕，原文另存，时间戳保持原视频位置。")
    result = document.model_copy(
        update={
            "segments": kept,
            "status": TranscriptStatus.READY if kept else TranscriptStatus.MISSING,
        }
    )
    return result, report, warnings
