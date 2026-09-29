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
        for update in data.get("provider_updates", []):
            relation = {
                "identical": "与当前标签相同",
                "ahead": f"多 {update['commits_ahead']} 个提交",
                "behind": "主分支较旧",
                "diverged": "历史已分叉",
                "unknown": "无法比较",
            }[update["branch_relation_to_installed_tag"]]
            typer.echo(
                f"{update['provider']}: 已装 {update['installed_version'] or '未安装'}，"
                f"包最新版 {update['latest_package_version'] or '未知'}，"
                f"上游主分支 {relation}"
            )
        for update in data.get("runtime_updates", {}).get("providers", []):
            label = {"updated": "已更新", "current": "已是最新", "external": "外部管理", "failed": "更新失败"}.get(
                update["status"], update["status"]
            )
            typer.echo(f"{update['provider']}: {label} {update.get('active_version') or ''}")
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
    from soota.auto_updates import automatic_update, should_update
    from soota.config import load_settings

    def execute() -> CommandResult:
        settings = load_settings()
        report = automatic_update(settings) if should_update(settings, fn, args, kwargs) else None
        try:
            result = fn(settings, *args, **kwargs)
        except SootaError as exc:
            if report:
                exc.details["runtime_updates"] = report
            raise
        if report:
            result.data["runtime_updates"] = report
            result.warnings.extend(report["warnings"])
        return result

    run(json_output, execute)
