from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from soota.config import SootaSettings
from soota.errors import ContractError, InputError, SourceError
from soota.providers.opencli_context import preflight, resolve_profile
from soota.providers.opencli_runtime import OpenCLIRuntime, RuntimeUnavailable
from soota.providers.process import run_process


def commands(settings: SootaSettings) -> list[dict[str, Any]]:
    if "opencli" in settings.routing.disabled_providers:
        raise RuntimeUnavailable("OpenCLI 已停用。")
    runtime = OpenCLIRuntime(settings)
    with runtime.lock():
        binary, _ = runtime.resolve()
        result = run_process([binary, "list", "-f", "json"], timeout=30, max_bytes=settings.opencli.max_output_bytes)
    try:
        rows = json.loads(result.stdout)
        if result.returncode or not isinstance(rows, list):
            raise ValueError
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("args"), list):
                raise ValueError
            for key in ("site", "name"):
                if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_-]*", row.get(key, "")):
                    raise ValueError
            if row.get("command") != f"{row['site']}/{row['name']}" or row["command"] in seen:
                raise ValueError
            if row.get("access") not in {"read", "write"} or not isinstance(row.get("browser"), bool):
                raise ValueError
            seen.add(row["command"])
        return rows
    except (ValueError, TypeError, KeyError) as exc:
        raise ContractError("OpenCLI 功能清单契约不兼容。") from exc


def argument_value(arg: dict[str, Any], value: Any) -> str:
    kind = arg.get("type", "str")
    if kind in {"bool", "boolean"}:
        if (
            value not in (True, False, "true", "false")
            or isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            raise InputError(f"{arg['name']} 必须是 true/false。")
        result = str(value).lower()
    elif kind in {"int", "number", "float"}:
        try:
            number = Decimal(str(value)) if kind == "int" else float(value)
            if isinstance(value, bool) or not math.isfinite(number) or kind == "int" and number != int(number):
                raise ValueError
        except (ValueError, TypeError, OverflowError, InvalidOperation) as exc:
            raise InputError(f"{arg['name']} 不是有效 {kind}。") from exc
        result = str(int(number)) if kind == "int" else str(number)
    elif kind in {"str", "string"}:
        if not isinstance(value, str):
            raise InputError(f"{arg['name']} 必须是字符串；ID 请在 JSON 中加引号。")
        result = value
    else:
        raise ContractError(f"尚不支持 OpenCLI 参数类型 {kind}。")
    choices = arg.get("choices")
    if choices and result not in {str(choice) for choice in choices}:
        raise InputError(f"{arg['name']} 不在允许的 choices 中。")
    if "\x00" in result:
        raise InputError("参数不能包含 NUL 字符。")
    return result


def command_arguments(command: dict[str, Any], params: dict[str, Any]) -> list[str]:
    args = command["args"]
    known = {arg["name"] for arg in args}
    if params.keys() - known:
        raise InputError("未知 OpenCLI 参数：" + ", ".join(sorted(params.keys() - known)))
    named: list[str] = []
    positional: list[str] = []
    gap = False
    for arg in args:
        name = arg["name"]
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_-]*", name):
            raise ContractError("OpenCLI 参数名无效。")
        if not arg.get("positional") and name not in params:
            if arg.get("required") and arg.get("default") is None:
                raise InputError(f"缺少必填参数 {name}。")
            continue
        value = params.get(name, arg.get("default"))
        if value is None:
            if arg.get("required"):
                raise InputError(f"缺少必填参数 {name}。")
            gap = gap or bool(arg.get("positional"))
            continue
        rendered = argument_value(arg, value)
        if arg.get("positional"):
            if gap:
                raise InputError("不能跳过中间的位置参数；请明确提供前置参数。")
            positional.append(rendered)
        else:
            named.append(f"--{name}={rendered}")
    return [*named, *(["--", *positional] if positional else [])]


def execute(settings: SootaSettings, command: dict[str, Any], params: dict[str, Any], *, allow_write: bool) -> Any:
    runtime = OpenCLIRuntime(settings)
    with runtime.lock():
        binary, _ = runtime.resolve()
        # Re-read under the same shared runtime lock held until dispatch completes.
        # An upgrade must not let old read metadata authorize a new write command.
        current = next((row for row in commands(settings) if row["command"] == command["command"]), None)
        if current is None:
            raise RuntimeUnavailable("当前运行时已不包含该功能。")
        command = current
        argv_args = command_arguments(command, params)
        if command["access"] == "write" and not allow_write:
            raise InputError("该功能会修改外部状态；请检查 features show 后显式加 --allow-write。")
        argv = [binary]
        if command["browser"]:
            version = run_process([binary, "--version"], timeout=15, max_bytes=65536)
            if version.returncode:
                raise RuntimeUnavailable("OpenCLI 无法启动。")
            profile = resolve_profile(settings.opencli.profile)
            preflight(version.stdout.strip(), profile)
            argv.extend(["--profile", profile])
        argv.extend([command["site"], command["name"], "-f", "json", *argv_args])
        result = run_process(
            argv, timeout=settings.opencli.timeout_seconds, max_bytes=settings.opencli.max_output_bytes
        )
    if result.returncode:
        # No retries/fallback after dispatch: a write or upstream charge may already have happened.
        raise SourceError("OpenCLI 执行失败；未自动重试。", details={"exit_code": result.returncode})
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ContractError("OpenCLI 没有返回有效 JSON；操作可能已执行，请先核对状态。") from exc
