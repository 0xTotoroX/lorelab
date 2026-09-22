from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from soota.api import _protect, call_endpoint, prepare_request
from soota.billing import selected_provider
from soota.config import SootaSettings
from soota.errors import InputError
from soota.feature_aliases import ALIASES, FeatureAlias, alias_params
from soota.models import CommandResult
from soota.providers import opencli_commands
from soota.providers.opencli_runtime import RuntimeUnavailable
from soota.providers.tikhub.registry import load_registry
from soota.secrets import CREDENTIAL_FIELDS


def success(message: str, data: dict[str, Any], warnings: list[str] | None = None) -> CommandResult:
    return CommandResult(
        ok=True, status="success", code="ok", exit_code=0, message=message, data=data, warnings=warnings or []
    )


def list_features(
    settings: SootaSettings,
    *,
    provider: str | None = None,
    site: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CommandResult:
    if provider not in {None, "opencli", "tikhub"} or not 1 <= limit <= 5000 or offset < 0:
        raise InputError("provider 支持 opencli/tikhub；limit 为 1–5000，offset 非负。")
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    if provider != "tikhub":
        try:
            for command in opencli_commands.commands(settings):
                rows.append(
                    {
                        "id": "opencli." + command["command"].replace("/", "."),
                        "site": command["site"],
                        "description": command.get("description", ""),
                        "providers": ["opencli"],
                        "access": command["access"],
                        "callable": True,
                        "browser": command["browser"],
                        "plans": [{"provider": "opencli", "operation": command["command"]}],
                    }
                )
        except RuntimeUnavailable as exc:
            warnings.append(exc.message + " OpenCLI 功能未载入；安装运行时后重新 list 即自动发现。")
    if provider != "opencli":
        for endpoint in load_registry().preferred():
            rows.append(
                {
                    "id": "tikhub." + endpoint.key,
                    "site": endpoint.platform,
                    "description": endpoint.summary,
                    "providers": ["tikhub"],
                    "access": "read" if endpoint.callable else "unclassified",
                    "callable": not endpoint.deprecated,
                    "requires_allow_write": not endpoint.callable,
                    "plans": [{"provider": "tikhub", "operation": endpoint.key}],
                    "reason": None if endpoint.callable else "辅助接口；需显式 --allow-write，价格未知时仍暂停",
                }
            )
    for alias in ALIASES:
        row = alias_view(settings, alias)
        if provider:
            row["plans"] = [plan for plan in row["plans"] if plan["provider"] == provider]
        rows.append(row)
    selected = [
        row
        for row in rows
        if (site is None or row["site"] == site)
        and (search is None or search.casefold() in f"{row['id']} {row['description']}".casefold())
    ]
    selected.sort(key=lambda row: row["id"])
    page = selected[offset : offset + limit]
    return success(
        f"找到 {len(selected)} 个功能入口，本页 {len(page)} 个。",
        {
            "features": page,
            "total": len(selected),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(selected) else None,
            "inventory": "OpenCLI 当前运行时动态发现；TikHub 随包版本化注册表；未逐一联网验收",
        },
        warnings,
    )


def alias_view(settings: SootaSettings, alias: FeatureAlias) -> dict[str, Any]:
    plans = [{"provider": "opencli", "operation": alias.opencli}, {"provider": "tikhub", "operation": alias.tikhub}]
    if settings.payment.default_provider == "tikhub":
        plans.reverse()
    return {
        "id": alias.id,
        "site": alias.id.split(".")[0],
        "description": alias.description,
        "providers": ["opencli", "tikhub"],
        "access": "read",
        "callable": True,
        "plans": plans,
        "required": [alias.parameter],
        "mapping": asdict(alias),
        "optional": {"sort": ["top", "latest"]} if alias.id == "twitter.post.search" else {},
        "output_contract": "provider_native",
        "payment": settings.payment.model_dump(),
    }


def resolve_opencli(settings: SootaSettings, selector: str) -> dict[str, Any]:
    for command in opencli_commands.commands(settings):
        if selector == "opencli." + command["command"].replace("/", "."):
            return command
    raise RuntimeUnavailable("当前 OpenCLI 运行时没有该功能。", hint="features list --provider opencli 查看当前能力。")


def show_feature(settings: SootaSettings, selector: str) -> CommandResult:
    alias = next((item for item in ALIASES if item.id == selector), None)
    if alias:
        return success(alias.description, {"feature": alias_view(settings, alias)})
    if selector.startswith("opencli."):
        command = resolve_opencli(settings, selector)
        return success("OpenCLI 原生功能契约。", {"feature": {"id": selector, **command}})
    if selector.startswith("tikhub."):
        endpoint = load_registry().resolve(selector.removeprefix("tikhub."))
        return success(
            "TikHub 原生功能契约。",
            {
                "feature": {
                    "id": selector,
                    **endpoint.model_dump(mode="json", by_alias=True),
                    "query_schema": endpoint.query_schema,
                }
            },
        )
    raise InputError("未知功能标识。", hint="使用 features list 查询完整 id。")


def read_params(params: list[str] | None, params_file: Path | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if params_file:
        try:
            values = json.loads(params_file.expanduser().read_text())
            if not isinstance(values, dict):
                raise ValueError
        except ValueError as exc:
            raise InputError("参数文件需要 JSON 对象。") from exc
    for pair in params or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise InputError("--param 使用 name=value。")
        if key in values:
            raise InputError(f"重复参数 {key}。")
        values[key] = value
    return values


def _native_opencli(
    settings: SootaSettings, selector: str, params: dict[str, Any], *, dry_run: bool, allow_write: bool
) -> CommandResult:
    command = resolve_opencli(settings, selector)
    arguments = opencli_commands.command_arguments(command, params)
    if dry_run:
        return success(
            "参数已校验；未执行业务命令。",
            {
                "plan": {
                    "provider": "opencli",
                    "operation": command["command"],
                    "access": command["access"],
                    "requires_allow_write": command["access"] == "write",
                    "arguments": arguments,
                    "tikhub_cost_usd": 0,
                    "native_service_cost": "unknown",
                }
            },
        )
    response = opencli_commands.execute(settings, command, params, allow_write=allow_write)
    return success(
        "已收到 OpenCLI 原生结果。",
        {
            "provider": "opencli",
            "operation": command["command"],
            "output_contract": "provider_native",
            "response": response,
            "tikhub_cost_usd": 0,
        },
    )


def call_feature(
    settings: SootaSettings,
    selector: str,
    *,
    params: list[str] | None = None,
    params_file: Path | None = None,
    body_file: Path | None = None,
    provider: str | None = None,
    dry_run: bool = False,
    max_cost: float | None = None,
    allow_write: bool = False,
    requester: Callable[..., Any] | None = None,
) -> CommandResult:
    chosen = selected_provider(settings, provider)
    if chosen not in {"auto", "opencli", "tikhub"}:
        raise InputError("provider 支持 auto/opencli/tikhub。")
    if selector.startswith("tikhub."):
        if provider == "opencli":
            raise InputError("原生 TikHub 功能不能指定 OpenCLI；请选择统一功能 id。")
        return call_endpoint(
            settings,
            selector.removeprefix("tikhub."),
            params=params,
            params_file=params_file,
            body_file=body_file,
            dry_run=dry_run,
            max_cost=max_cost,
            requester=requester,
            allow_auxiliary=allow_write,
        )
    values = read_params(params, params_file)
    secrets = [str(value) for key, value in values.items() if key.lower() in CREDENTIAL_FIELDS]
    if body_file:
        raise InputError("--body 仅适用于 tikhub.* 原生功能。")
    if selector.startswith("opencli."):
        if provider == "tikhub":
            raise InputError("原生 OpenCLI 功能不能指定 TikHub；请选择统一功能 id。")
        result = _native_opencli(settings, selector, values, dry_run=dry_run, allow_write=allow_write)
    else:
        alias = next((item for item in ALIASES if item.id == selector), None)
        if alias is None:
            raise InputError("未知功能标识。", hint="使用 features list 查询完整 id。")
        cheap, paid = alias_params(alias, values)
        secrets.extend(str(v) for k, v in paid.items() if k.lower() in CREDENTIAL_FIELDS)
        endpoint = load_registry().resolve(alias.tikhub)
        paid_pairs = [f"{key}={value}" for key, value in paid.items()]
        # Validate the mapped paid plan offline too, so a bad alias never silently charges.
        prepare_request(endpoint, paid_pairs, None, None)
        result = None
        unavailable: str | None = None
        if chosen != "tikhub":
            try:
                result = _native_opencli(
                    settings, "opencli." + alias.opencli.replace("/", "."), cheap, dry_run=dry_run, allow_write=False
                )
            except RuntimeUnavailable as exc:
                if chosen == "opencli":
                    raise
                unavailable = exc.message
        if result is None:
            result = call_endpoint(
                settings, alias.tikhub, params=paid_pairs, dry_run=dry_run, max_cost=max_cost, requester=requester
            )
            result.data.update(provider="tikhub", operation=alias.tikhub, output_contract="provider_native")
        plans = alias_view(settings, alias)["plans"]
        plans.sort(key=lambda plan: plan["provider"] != ("tikhub" if chosen == "tikhub" else "opencli"))
        result.data["feature"] = {"id": alias.id, "plans": plans}
        if unavailable:
            result.warnings.append(unavailable + " 已按当前费用策略选择 TikHub。")
    assert result is not None
    result.data = _protect(result.data, secrets)
    return result
