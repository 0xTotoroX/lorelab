from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from soota.config import SootaSettings
from soota.errors import AuthBudgetError, ContractError, SourceError
from soota.models import CapabilitySet, CatalogPage, MediaItem, RequestRecord, SourceRef
from soota.providers.opencli_context import preflight, resolve_profile
from soota.providers.opencli_runtime import OpenCLIRuntime, RuntimeUnavailable
from soota.providers.process import run_process
from soota.storage.cache import CacheStore

ALLOWLIST = {("twitter", "tweets"), ("bilibili", "video"), ("youtube", "video")}


def capabilities_for(source: SourceRef) -> CapabilitySet:
    if source.platform == "twitter" and source.kind == "user":
        return CapabilitySet(catalog=True)
    if source.kind == "video" and (
        source.platform == "youtube" or source.platform == "bilibili" and source.id.startswith("BV")
    ):
        return CapabilitySet(inspect=True)
    return CapabilitySet()


class OpenCLIProvider:
    name = "opencli"

    def __init__(self, settings: SootaSettings) -> None:
        self.settings = settings
        self.runtime = OpenCLIRuntime(settings)
        self.profile = resolve_profile(settings.opencli.profile)
        scope = hashlib.sha256(self.profile.encode()).hexdigest()[:16]
        self.cache = CacheStore(settings.cache_dir / "opencli" / scope)
        self.records: list[RequestRecord] = []
        self.version: str | None = None

    def _run(self, site: str, command: str, args: list[str]) -> list[dict[str, Any]]:
        if (site, command) not in ALLOWLIST:
            raise ContractError("该 OpenCLI 命令不在 Soota 的只读白名单内。")
        with self.runtime.lock():
            binary, _ = self.runtime.resolve()
            version = run_process([binary, "--version"], timeout=15, max_bytes=65536)
            if version.returncode:
                raise RuntimeUnavailable("OpenCLI 无法启动。")
            self.version = version.stdout.strip()
            preflight(self.version, self.profile)
            argv = [binary]
            if self.profile:
                argv += ["--profile", self.profile]
            argv += [site, command, *args, "-f", "json"]
            try:
                result = run_process(
                    argv,
                    timeout=self.settings.opencli.timeout_seconds,
                    max_bytes=self.settings.opencli.max_output_bytes,
                )
            except FileNotFoundError as exc:
                raise RuntimeUnavailable("OpenCLI 程序已不可用。") from exc
        self.records.append(
            RequestRecord(
                endpoint=f"opencli:{site}/{command}", billed=False, estimated_cost_usd=0, note=f"version:{self.version}"
            )
        )
        if result.returncode:
            # Never return raw stderr: extensions and pages may include login/account details.
            message = result.stderr.lower()
            if result.returncode == 77 or any(
                token in message
                for token in (
                    "429",
                    "rate_limit",
                    "rate limit",
                    "captcha",
                    "login_required",
                    "unauthorized",
                    "forbidden",
                )
            ):
                raise AuthBudgetError("OpenCLI 登录、限流或访问限制，需要处理浏览器状态后再试；不会切换付费来源。")
            code = re.search(r"(?m)^\s*code:\s*['\"]?([A-Z_]+)", result.stderr)
            bridge_missing = any(phrase in message for phrase in ("extension not connected", "daemon not running"))
            if result.returncode == 69 and code and code[1] == "BROWSER_CONNECT" and bridge_missing:
                raise RuntimeUnavailable(
                    "OpenCLI Browser Bridge 不可用。", hint="检查 Chrome 和 Browser Bridge 扩展连接。"
                )
            raise SourceError("OpenCLI 采集失败，未自动重试或切换来源。", details={"exit_code": result.returncode})
        try:
            rows = json.loads(result.stdout)
        except ValueError as exc:
            raise ContractError("OpenCLI 未返回有效 JSON。") from exc
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ContractError("OpenCLI JSON 必须是对象数组。")
        return rows

    def provenance(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "runtime_version": self.version,
            "profile": self.profile or "default",
            "captured_at": datetime.now(UTC).isoformat(),
        }

    def inspect(self, source: SourceRef) -> MediaItem:
        if not capabilities_for(source).inspect:
            raise SourceError("OpenCLI 尚未接入该来源的元数据命令。")
        cached = self.cache.get_json(source, "inspect")
        if cached and 0 <= time.time() - cached.get("timestamp", 0) < self.settings.opencli.metadata_cache_seconds:
            item = MediaItem.model_validate(cached["item"])
            if item.source.cache_identity != source.cache_identity:
                raise ContractError("OpenCLI 缓存来源不匹配。")
            self.records.append(
                RequestRecord(endpoint="opencli:cache:inspect", billed=False, cache_hit=True, estimated_cost_usd=0)
            )
            return item
        rows = self._run(source.platform, "video", [source.id])
        item = normalize_video(source, rows)
        item.provenance = self.provenance()
        self.cache.put_json(source, "inspect", {"timestamp": time.time(), "item": item.model_dump(mode="json")})
        return item

    def resolve_catalog_source(self, source: SourceRef) -> SourceRef:
        if not capabilities_for(source).catalog:
            raise SourceError("OpenCLI 目录只接入 X 最近帖子快照。")
        return source

    def list_items(self, source: SourceRef, cursor: str | None = None, *, page_size: int = 100) -> CatalogPage:
        self.resolve_catalog_source(source)
        if cursor is not None or not 1 <= page_size <= 200:
            raise ContractError("OpenCLI 最近帖子仅支持 1–200 条快照，没有可续跑的分页游标。")
        rows = self._run("twitter", "tweets", [source.id, "--limit", str(page_size)])
        items: list[MediaItem] = []
        invalid = 0
        for row in rows[:page_size]:
            ident, body = row.get("id"), row.get("text")
            if not isinstance(ident, str) or not re.fullmatch(r"[0-9]+", ident) or not isinstance(body, str):
                invalid += 1
                continue
            author = str(row.get("author") or source.id).lstrip("@")
            handle = author if re.fullmatch(r"[A-Za-z0-9_]{1,15}", author) else source.id
            url = f"https://x.com/{handle}/status/{ident}"
            post = SourceRef(platform="twitter", kind="post", id=ident, url=url, canonical_url=url)
            items.append(
                MediaItem(
                    source=post,
                    title=body[:100],
                    text=body,
                    creator=author,
                    published_at=parse_date(row.get("created_at")),
                    provenance=self.provenance(),
                    extras={
                        key: json.dumps(value, ensure_ascii=False)
                        for key, value in row.items()
                        if key not in {"id", "text", "author", "url", "created_at"}
                    },
                )
            )
        warnings = ["最近帖子快照；上游可能静默返回部分结果，完整性未知，不代表全部历史或已追平。"]
        if invalid:
            warnings.append(f"{invalid} 条不符合契约；有效条目已保留。")
        if rows and not items:
            raise ContractError("OpenCLI 帖子响应没有可用的稳定 ID 和正文。")
        return CatalogPage(items=items, title=f"@{source.id}", completeness="unknown", warnings=warnings)


def parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None
    return result if result.tzinfo else result.replace(tzinfo=UTC)


def normalize_video(source: SourceRef, rows: list[dict[str, Any]]) -> MediaItem:
    fields: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row.get("field"), str) or "value" not in row or row["field"] in fields:
            raise ContractError("OpenCLI 元数据 field/value 契约不匹配。")
        fields[row["field"]] = row["value"]
    ident_key = "videoId" if source.platform == "youtube" else "bvid"
    if fields.get(ident_key) != source.id or not isinstance(fields.get("title"), str) or not fields["title"]:
        raise ContractError("OpenCLI 返回了不同视频或缺少标题。")
    duration = re.search(r"(?:^|\()(\d+)s\)?$", str(fields.get("duration", "")))
    return MediaItem(
        source=source,
        title=fields["title"],
        creator=str(fields.get("channel" if source.platform == "youtube" else "author") or "") or None,
        published_at=parse_date(fields.get("publishDate" if source.platform == "youtube" else "publish_time")),
        duration_seconds=int(duration[1]) if duration else None,
        extras={str(key): str(value) for key, value in fields.items() if value is not None},
    )
