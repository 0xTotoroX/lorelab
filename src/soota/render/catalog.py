from __future__ import annotations

import html
import json
import re
from pathlib import Path

from soota.models import CatalogJob, MediaItem
from soota.secrets import redact_any
from soota.storage.atomic import atomic_write


def _text(value: str) -> str:
    return re.sub(r"([\\`*_\[\]|])", r"\\\1", html.escape(" ".join(value.split()), quote=False))


def _row(index: int, item: MediaItem) -> str:
    title = _text(item.title or item.source.id)
    creator = _text(item.creator or "—")
    published = item.published_at.date().isoformat() if item.published_at else item.extras.get("published_label", "—")
    duration = "—"
    if item.duration_seconds is not None:
        minutes, seconds = divmod(item.duration_seconds, 60)
        duration = f"{minutes}:{seconds:02d}"
    return f"| {index} | [{title}]({item.source.canonical_url}) | {creator} | {_text(published)} | {duration} |"


def write_catalog(job: CatalogJob, reserved_cost: float) -> Path:
    folder = job.output_root / "catalogs" / job.id
    payload = {
        "schema_version": 1,
        "job_id": job.id,
        "source": job.source.model_dump(mode="json"),
        "title": job.title,
        "updated_at": job.updated_at,
        "status": job.status,
        "stop_reason": job.stop_reason,
        "incremental": job.incremental,
        "item_count": len(job.items),
        "pages_fetched": job.pages_fetched,
        "items": [item.model_dump(mode="json") for item in job.items],
        "processing": {
            "provider": "tikhub",
            "reserved_cost_usd": reserved_cost,
            "actual_cost_usd": None,
            "requests": [record.model_dump(mode="json") for record in job.requests],
        },
        "error": job.error,
    }
    title = _text(job.title or job.source.id)
    lines = [
        f"# {title} · 视频目录",
        "",
        f"来源：{job.source.canonical_url}",
        f"任务：`{job.id}` · 状态：`{job.status}` · 条目：{len(job.items)} · 已读取页面：{job.pages_fetched}",
        "",
        "本目录仅保存视频链接与已有元数据，不包含字幕、转写或摘要。",
    ]
    if job.incremental:
        lines.extend(["", "这是增量目录，只列出此前目录任务中尚未收录的条目。"])
    if job.status != "completed":
        lines.extend(
            ["", f"当前目录尚未完成（{job.stop_reason}），进度已保存。", f"续跑：`soota jobs resume {job.id}`"]
        )
    lines.extend(["", "| # | 视频 | 作者 | 发布时间 | 时长 |", "| --- | --- | --- | --- | --- |"])
    lines.extend(_row(index, item) for index, item in enumerate(job.items, 1))
    lines.extend(["", f"请求预算已预留 {reserved_cost:g} USD；实际扣费以 TikHub 账单为准。", ""])
    atomic_write(folder / "catalog.json", json.dumps(redact_any(payload), ensure_ascii=False, indent=2) + "\n")
    atomic_write(folder / "catalog.md", "\n".join(lines))
    return folder
