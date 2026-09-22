from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import typer

from soota.errors import SootaError, StorageError
from soota.models import CommandResult
from soota.secrets import redact_any


def emit(result: CommandResult, json_output: bool) -> None:
    payload = redact_any(result.model_dump())
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(payload["message"])
        if payload["hint"]:
            typer.echo(f"hint: {payload['hint']}", err=True)
        for warning in payload["warnings"]:
            typer.echo(f"warning: {warning}", err=True)
        data = payload["data"]
        for key in ("policy", "feature", "plan"):
            if key in data:
                typer.echo(json.dumps(data[key], ensure_ascii=False, indent=2, default=str))
        for feature in data.get("features", []):
            typer.echo(f"{feature['id']}  {feature['description']}")
        if data.get("output"):
            typer.echo(f"output: {data['output']}")
        if data.get("job_id"):
            typer.echo(f"job: {data['job_id']}")
        for job in data.get("jobs", []):
            typer.echo(f"{job['id']}  {job.get('kind', 'ingest')}  {job.get('status', 'unknown')}")
        for platform in data.get("platforms", []):
            typer.echo(f"{platform['platform']:18} {platform['name']:14} API: {platform['api_operations']}")
        for endpoint in data.get("endpoints", []):
            if isinstance(endpoint, dict):
                typer.echo(f"{endpoint['key']}  {endpoint['method']} {endpoint['path']}")
                typer.echo(f"  {endpoint['summary']}")
        if "query_schema" in data:
            typer.echo(json.dumps(data["endpoint"], ensure_ascii=False, indent=2))
        if "response" in data:
            typer.echo(json.dumps(data["response"], ensure_ascii=False, indent=2))
        if "request" in data:
            typer.echo(f"endpoint: {data['request']['method']} {data['request']['path']}")
        if "estimated_cost_usd" in data:
            typer.echo(f"estimated cost: {data['estimated_cost_usd']} USD")
        if "reserved_cost_usd" in data:
            typer.echo(f"reserved cost: {data['reserved_cost_usd']} USD")
    raise typer.Exit(result.exit_code)


def fail(exc: SootaError, json_output: bool) -> None:
    payload = redact_any(exc.to_dict())
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(payload["message"], err=True)
        if payload.get("hint"):
            typer.echo(f"hint: {payload['hint']}", err=True)
    raise typer.Exit(exc.exit_code)


def run(json_output: bool, fn: Callable[..., CommandResult], *args: Any, **kwargs: Any) -> None:
    try:
        result = fn(*args, **kwargs)
    except SootaError as exc:
        fail(exc, json_output)
        return
    except OSError:
        fail(StorageError("无法读写本地文件。", hint="检查配置、任务和输出目录是否可写。"), json_output)
        return
    emit(result, json_output)


def run_settings(json_output: bool, fn: Callable[..., CommandResult], *args: Any, **kwargs: Any) -> None:
    from soota.config import load_settings

    run(json_output, lambda: fn(load_settings(), *args, **kwargs))
