"""
[INPUT]: Settings, credential file and priority planner
[OUTPUT]: providers and priority CLI groups
[POS]: User configuration entry point
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from soota.cli_output import run
from soota.config import PriorityRule, SootaSettings, load_settings
from soota.errors import InputError
from soota.models import CommandResult, SourceRef
from soota.providers.monid.client import load_key
from soota.providers.priority import CAPABILITIES, NAMES, ordered_names, quote_rows, rule_for
from soota.providers.tikhub.registry import PLATFORM_NAMES, load_registry
from soota.storage.atomic import atomic_write

app = typer.Typer(help="启用来源、配置 Monid 凭据，按平台和能力查看或设置优先级。")
priority_app = typer.Typer(help="cost 按报价排序；manual 使用指定顺序，未列来源排在后面。")
app.add_typer(priority_app, name="priority")


def result(message: str, data: dict[str, Any]) -> CommandResult:
    return CommandResult(ok=True, status="success", code="ok", exit_code=0, message=message, data=data)


def save(settings: SootaSettings) -> None:
    atomic_write(
        settings.config_dir / "providers.json",
        json.dumps(
            {"routing": settings.routing.model_dump(mode="json"), "monid": settings.monid.model_dump(mode="json")},
            ensure_ascii=False,
            indent=2,
        ),
    )


def toggle(name: str, enabled: bool) -> CommandResult:
    if name not in NAMES:
        raise InputError("未知来源。")
    settings = load_settings()
    if name == "opencli-mcp" and enabled and not settings.opencli_mcp.enabled:
        raise InputError("MCP 需先在 config.toml 的 opencli_mcp.enabled 显式开启。")
    if enabled:
        settings.routing.disabled_providers.discard(name)
    else:
        settings.routing.disabled_providers.add(name)  # type: ignore[arg-type]
    if name == "monid":
        settings.monid.enabled = enabled
    save(settings)
    return result("来源策略已保存；付费确认模式未改变。", {"provider": name, "enabled": enabled})


@app.command()
def enable(name: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run(json_output, lambda: toggle(name, True))


@app.command()
def disable(name: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run(json_output, lambda: toggle(name, False))


@app.command()
def show(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    def show_result() -> CommandResult:
        settings = load_settings()
        return result(
            "当前来源配置。",
            {
                "routing": settings.routing.model_dump(mode="json"),
                "monid": settings.monid.model_dump(),
                "monid_key_present": bool(load_key(settings)),
            },
        )

    run(json_output, show_result)


@app.command()
def auth(
    name: str,
    key_file: Annotated[Path | None, typer.Option("--key-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    def configure() -> CommandResult:
        if name != "monid":
            raise InputError("此命令配置 Monid；TikHub 沿用 TIKHUB_API_KEY 或 Keychain。")
        key = key_file.expanduser().read_text().strip() if key_file else typer.prompt("Monid API Key", hide_input=True)
        if not key or any(ch.isspace() for ch in key):
            raise InputError("API Key 不能为空或包含空白。")
        path = load_settings().config_dir / "credentials" / "monid.key"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(path, key + "\n")
        path.chmod(0o600)
        return result("Monid Key 已保存到本机配置目录；不会显示密钥。", {"configured": True})

    run(json_output, configure)


def source_for(platform: str, capability: str) -> SourceRef:
    if platform not in PLATFORM_NAMES and platform != "*":
        raise InputError("未知平台；用 soota platforms 查看平台标识。")
    kind = ("channel" if platform == "youtube" else "user") if capability == "catalog" else "video"
    return SourceRef(
        platform=platform,
        kind=kind,
        id="BV0000000000" if platform == "bilibili" else "priority-preview",
        url="",
        canonical_url="",
    )


@priority_app.command("set")
def set_priority(
    platform: str,
    capability: str,
    mode: Annotated[str, typer.Option("--mode")] = "cost",
    order: Annotated[str | None, typer.Option("--order", help="逗号分隔；manual 必填")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    def configure() -> CommandResult:
        source_for(platform, capability)
        if capability not in CAPABILITIES:
            raise InputError("能力支持 inspect/captions/catalog/api/audio。")
        names = [n.strip() for n in order.split(",")] if order else []
        if mode == "manual" and not names:
            raise InputError("manual 需要 --order。")
        try:
            rule = PriorityRule.model_validate({"mode": mode, "order": names})
        except ValueError as exc:
            raise InputError("模式或来源顺序无效，不能包含未知或重复来源。") from exc
        settings = load_settings()
        settings.routing.priorities.setdefault(platform, {})[capability] = rule
        save(settings)
        return result("优先级已保存。", {"platform": platform, "capability": capability, **rule.model_dump()})

    run(json_output, configure)


@priority_app.command("show")
def show_priority(
    platform: str,
    capability: Annotated[str, typer.Argument()] = "captions",
    endpoint: Annotated[str | None, typer.Option("--endpoint")] = None,
    refresh: Annotated[bool, typer.Option("--refresh", help="免费查询实时单价")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    def preview() -> CommandResult:
        settings = load_settings()
        source = source_for(platform, capability)
        path = load_registry().resolve(endpoint).path if endpoint else None
        if capability == "api" and path is None:
            raise InputError("api 报价需提供 --endpoint；不同接口不混合比较。")
        if path and path.split("/")[3] != platform:
            raise InputError("接口不属于所选平台。")
        names = ["tikhub", "monid"] if capability == "api" else list(NAMES)
        if capability == "audio":
            names = ["yt-dlp", "tikhub", "monid"]
        rows = quote_rows(settings, source, capability, names, endpoint=path, refresh=refresh)
        return result(
            "来源报价和有效顺序；不包含重试、折扣或转写费用。",
            {
                "platform": platform,
                "capability": capability,
                "rule": rule_for(settings, platform, capability).model_dump(),
                "order": ordered_names(settings, source, capability, names, endpoint=path),
                "candidates": rows,
            },
        )

    run(json_output, preview)
