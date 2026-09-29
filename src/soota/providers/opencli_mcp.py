from __future__ import annotations

import hashlib
import math
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from soota.config import SootaSettings
from soota.errors import AuthBudgetError, ContractError, InputError, SourceError
from soota.models import (
    CapabilitySet,
    CaptionResult,
    CatalogPage,
    MediaItem,
    RequestRecord,
    SourceRef,
    TranscriptSegment,
    TranscriptSource,
    TranscriptStatus,
)
from soota.providers.mcp_client import MCPToolError, StdioMCPClient, require_enabled
from soota.providers.opencli import parse_date
from soota.storage.cache import CacheStore

READ_COMMANDS = {
    ("bilibili", "video"): "bilibili.com",
    ("bilibili", "subtitle"): "bilibili.com",
    ("twitter", "tweets"): "x.com",
}


def capabilities_for(source: SourceRef) -> CapabilitySet:
    if source.platform == "bilibili" and source.kind == "video" and source.id.startswith("BV"):
        return CapabilitySet(inspect=True, captions=True)
    if source.platform == "twitter" and source.kind == "user":
        return CapabilitySet(catalog=True)
    return CapabilitySet()


class OpenCLIMCPProvider:
    name = "opencli-mcp"

    def __init__(self, settings: SootaSettings) -> None:
        require_enabled(settings.opencli_mcp)
        self.settings = settings
        scope = hashlib.sha256(str(settings.opencli_mcp.binary or "default").encode()).hexdigest()[:16]
        self.cache = CacheStore(settings.cache_dir / "opencli-mcp" / scope)
        self.records: list[RequestRecord] = []

    def _run(self, site: str, command: str, args: dict[str, Any]) -> dict[str, Any]:
        if (site, command) not in READ_COMMANDS:
            raise InputError("该 opencli-mcp 命令不在 Soota 只读白名单。")
        if not StdioMCPClient.available(self.settings.opencli_mcp):
            from soota.providers.opencli_runtime import RuntimeUnavailable

            raise RuntimeUnavailable("opencli-mcp 未安装。")
        self.records.append(RequestRecord(endpoint=f"opencli-mcp:{site}/{command}", billed=False, estimated_cost_usd=0))
        try:
            return StdioMCPClient(self.settings.opencli_mcp).call_site_readonly(
                site, command, args, expected_domain=READ_COMMANDS[(site, command)]
            )
        except MCPToolError as exc:
            if exc.upstream_code in {"auth_required", "rate_limited", "captcha_required", "access_denied"}:
                raise AuthBudgetError("opencli-mcp 登录、限流或访问限制；不会自动切换来源。") from exc
            raise

    def provenance(self) -> dict[str, Any]:
        return {"provider": self.name, "captured_at": datetime.now(UTC).isoformat()}

    def inspect(self, source: SourceRef) -> MediaItem:
        if not capabilities_for(source).inspect:
            raise SourceError("opencli-mcp 尚未接入该来源的元数据。")
        cached = self.cache.get_json(source, "inspect")
        if cached and 0 <= time.time() - cached.get("timestamp", 0) < self.settings.opencli_mcp.metadata_cache_seconds:
            item = MediaItem.model_validate(cached["item"])
            if item.source.cache_identity != source.cache_identity:
                raise ContractError("opencli-mcp 缓存来源不匹配。")
            self.records.append(
                RequestRecord(endpoint="opencli-mcp:cache:inspect", billed=False, cache_hit=True, estimated_cost_usd=0)
            )
            return item
        response = self._run("bilibili", "video", {"bvid": source.id})
        rows = response.get("rows")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ContractError("opencli-mcp 视频详情必须返回单条记录。")
        item = normalize_video(source, rows[0])
        item.provenance = self.provenance()
        self.cache.put_json(source, "inspect", {"timestamp": time.time(), "item": item.model_dump(mode="json")})
        return item

    def get_captions(self, item: MediaItem) -> CaptionResult:
        source = item.source
        if not capabilities_for(source).captions:
            raise SourceError("opencli-mcp 尚未接入该来源的字幕。")
        language = self.settings.default_language
        artifact = "captions-" + hashlib.sha256(language.encode()).hexdigest()[:12]
        cached = self.cache.get_json(source, artifact)
        if cached and 0 <= time.time() - cached.get("timestamp", 0) < self.settings.opencli_mcp.metadata_cache_seconds:
            result = CaptionResult.model_validate(cached["result"])
            if result.status == TranscriptStatus.READY and result.segments:
                self.records.append(
                    RequestRecord(
                        endpoint="opencli-mcp:cache:captions", billed=False, cache_hit=True, estimated_cost_usd=0
                    )
                )
                return result
        try:
            response = self._run("bilibili", "subtitle", {"bvid": source.id, "lang": language})
        except MCPToolError as exc:
            if exc.upstream_code == "empty_result":
                return CaptionResult(status=TranscriptStatus.MISSING)
            raise
        rows = response.get("rows")
        if not isinstance(rows, list):
            raise ContractError("opencli-mcp 字幕响应缺少 rows。")
        result = normalize_captions(rows)
        if result.status == TranscriptStatus.READY:
            self.cache.put_json(
                source,
                artifact,
                {"timestamp": time.time(), "result": result.model_dump(mode="json"), "requested_language": language},
            )
        return result

    def list_items(self, source: SourceRef, cursor: str | None = None, *, page_size: int = 100) -> CatalogPage:
        if not capabilities_for(source).catalog:
            raise SourceError("opencli-mcp 目录目前只接入 X 最近帖子。")
        if cursor is not None or not 1 <= page_size <= 100:
            raise InputError("opencli-mcp 的 X 快照最多 100 条；Soota 尚未接入续页。")
        response = self._run("twitter", "tweets", {"username": source.id, "limit": page_size})
        rows = response.get("rows")
        if not isinstance(rows, list):
            raise ContractError("opencli-mcp 帖子响应缺少 rows。")
        items: list[MediaItem] = []
        for row in rows[:page_size]:
            if not isinstance(row, dict):
                raise ContractError("opencli-mcp 帖子不是对象。")
            ident, body = row.get("id"), row.get("text")
            if not isinstance(ident, str) or not ident.isascii() or not ident.isdigit() or not isinstance(body, str):
                raise ContractError("opencli-mcp 帖子缺少稳定 ID 或正文。")
            url = f"https://x.com/{source.id}/status/{ident}"
            post = SourceRef(platform="twitter", kind="post", id=ident, url=url, canonical_url=url)
            items.append(
                MediaItem(
                    source=post,
                    title=body[:100],
                    text=body,
                    creator=str(row.get("author") or source.id),
                    published_at=parse_date(row.get("created_at")),
                    provenance=self.provenance(),
                )
            )
        return CatalogPage(
            items=items,
            title=f"@{source.id}",
            completeness="unknown",
            warnings=["最近帖子快照；上游可能返回部分结果，不代表全部历史或已追平。"],
        )

    def resolve_catalog_source(self, source: SourceRef) -> SourceRef:
        if not capabilities_for(source).catalog:
            raise SourceError("opencli-mcp 目录目前只接入 X 最近帖子。")
        return source


def normalize_video(source: SourceRef, row: dict[str, Any]) -> MediaItem:
    if row.get("bvid") != source.id or not isinstance(row.get("title"), str) or not row["title"]:
        raise ContractError("opencli-mcp 返回了不同视频或缺少标题。")
    duration = row.get("duration_s")
    if (
        isinstance(duration, bool)
        or duration is not None
        and (not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0)
    ):
        raise ContractError("opencli-mcp 视频时长无效。")
    return MediaItem(
        source=source,
        title=row["title"],
        creator=str(row.get("author") or "") or None,
        published_at=parse_date(row.get("published")),
        duration_seconds=int(duration) if duration is not None else None,
        extras={key: str(row[key]) for key in ("aid", "category", "url") if row.get(key) is not None},
    )


def normalize_captions(rows: list[Any]) -> CaptionResult:
    segments: list[TranscriptSegment] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("content"), str):
            raise ContractError("opencli-mcp 字幕正文契约不匹配。")
        try:
            start = Decimal(str(row["from_s"]))
            end = Decimal(str(row["to_s"]))
        except (KeyError, InvalidOperation) as exc:
            raise ContractError("opencli-mcp 字幕时间戳契约不匹配。") from exc
        if not start.is_finite() or not end.is_finite() or start < 0 or end < start:
            raise ContractError("opencli-mcp 字幕时间范围无效。")
        if row["content"].strip():
            segments.append(
                TranscriptSegment(
                    segment_id=f"seg-{len(segments) + 1:06d}",
                    start_ms=int(start * 1000),
                    end_ms=int(end * 1000),
                    text=row["content"].strip(),
                    language=None,
                    source=TranscriptSource.UNKNOWN,
                )
            )
    return CaptionResult(
        status=TranscriptStatus.READY if segments else TranscriptStatus.MISSING,
        source=TranscriptSource.UNKNOWN if segments else None,
        language=None,
        segments=segments,
    )
