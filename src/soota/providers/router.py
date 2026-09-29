from __future__ import annotations

import math
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal

from soota.billing import PaymentGate
from soota.config import SootaSettings
from soota.errors import AuthBudgetError, InputError, SourceError
from soota.models import MediaItem, RequestRecord, SourceRef
from soota.providers.opencli import OpenCLIProvider
from soota.providers.opencli import capabilities_for as opencli_capabilities
from soota.providers.opencli_mcp import OpenCLIMCPProvider
from soota.providers.opencli_mcp import capabilities_for as mcp_capabilities
from soota.providers.opencli_runtime import RuntimeUnavailable
from soota.providers.soota import SootaProvider
from soota.providers.soota import capabilities_for as soota_capabilities
from soota.providers.tikhub.capability import capabilities_for as tikhub_capabilities
from soota.providers.tikhub.client import TikHubProvider
from soota.storage.cache import CacheStore

ProviderName = Literal["auto", "opencli-mcp", "opencli", "soota", "tikhub"]


def validate_policy(provider: str, fallback: str | None, max_cost: float | None) -> None:
    if provider not in {"auto", "opencli-mcp", "opencli", "soota", "tikhub"} or fallback not in {None, "tikhub"}:
        raise InputError("--provider 支持 auto/opencli-mcp/opencli/soota/tikhub；--fallback 只支持 tikhub。")
    if fallback and provider == "tikhub":
        raise InputError("TikHub 已是指定来源，无需再指定同名 fallback。")
    if max_cost is not None and (not math.isfinite(max_cost) or max_cost < 0):
        raise InputError("--max-cost 必须是有限的非负数。")
    if fallback and max_cost == 0:
        raise InputError("--max-cost 0 禁止 TikHub 付费兜底。")


def catalog_provider(
    source: SourceRef, provider: str, *, mcp_available: bool = False
) -> Literal["opencli-mcp", "opencli", "tikhub"]:
    if provider == "soota":
        raise SourceError("soota 尚未接入目录能力。")
    if (provider == "opencli-mcp" or provider == "auto" and mcp_available) and mcp_capabilities(source).catalog:
        return "opencli-mcp"
    if provider == "opencli-mcp":
        raise SourceError("opencli-mcp 尚未接入该目录能力。")
    if provider != "tikhub" and opencli_capabilities(source).catalog:
        return "opencli"
    if provider != "opencli" and tikhub_capabilities(source).catalog:
        return "tikhub"
    raise SourceError("指定来源不具备该目录能力。", hint="X 使用 OpenCLI 最近快照；YouTube/Bilibili 目录使用 TikHub。")


class RequestBudget:
    def __init__(self, cap: float) -> None:
        self.cap = Decimal(str(cap))
        self.spent = Decimal(0)

    def reserve(self, record: RequestRecord) -> None:
        if not record.billed or record.cache_hit:
            return
        price = record.estimated_cost_usd
        if self.cap == 0 or price is None or not math.isfinite(price) or price < 0:
            raise AuthBudgetError("零预算禁止付费请求；未知价格也不会执行。")
        cost = Decimal(str(price))
        if self.spent + cost > self.cap:
            raise AuthBudgetError("下一次请求将超过费用上限，已在请求前停止。")
        self.spent += cost


def inspect_item(
    settings: SootaSettings,
    source: SourceRef,
    *,
    provider: str = "auto",
    fallback: str | None = None,
    max_cost: float | None = None,
    requester: Callable[..., Any] | None = None,
) -> tuple[MediaItem, list[RequestRecord], list[str]]:
    validate_policy(provider, fallback, max_cost)
    if provider == "auto" and fallback is None and max_cost != 0:
        fallback = "tikhub"
    warnings: list[str] = []
    records: list[RequestRecord] = []
    for name, capability, factory in (
        ("opencli-mcp", mcp_capabilities(source).inspect, OpenCLIMCPProvider),
        ("opencli", opencli_capabilities(source).inspect, OpenCLIProvider),
        ("soota", soota_capabilities(source).inspect, SootaProvider),
    ):
        if name == "opencli-mcp" and not settings.opencli_mcp.enabled:
            if provider == name:
                raise InputError("MCP 接入已停用。")
            continue
        if provider not in {"auto", name}:
            continue
        if not capability:
            if provider == name:
                raise SourceError(f"{name} 尚不具备该元数据能力。")
            continue
        cheap: OpenCLIMCPProvider | OpenCLIProvider | SootaProvider | None = None
        try:
            cheap = factory(settings)
            item = cheap.inspect(source)
            return item, [*records, *cheap.records], warnings
        except RuntimeUnavailable as exc:
            if provider != "auto" and fallback != "tikhub":
                raise
            warnings.append(f"{name} 不可用：{exc.message}")
            if cheap is not None:
                records.extend(cheap.records)
    if provider != "tikhub" and fallback != "tikhub":
        raise SourceError("没有匹配的免费元数据来源。", hint="可显式选择 --provider tikhub 并提供 --max-cost。")
    if not tikhub_capabilities(source).inspect:
        raise SourceError("TikHub 尚未接入该来源的统一元数据解析。")
    paid = TikHubProvider(
        runtime_python=settings.tikhub.runtime_python,
        cache=CacheStore(settings.cache_dir),
        base_url=settings.tikhub.base_url,
        timeout=settings.tikhub.timeout_seconds,
        preferred_language=settings.default_language,
        requester=requester,
        before_request=RequestBudget(max_cost).reserve if max_cost is not None else None,
        max_retries=0,
        payment_gate=PaymentGate(settings, max_cost),
    )
    item = paid.inspect(source)
    item.provenance = {"provider": "tikhub", "cache_hit": any(r.cache_hit for r in paid.records)}
    records.extend(paid.records)
    return item, records, warnings
