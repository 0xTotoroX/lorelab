from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from soota.config import load_settings
from soota.errors import SootaError
from soota.models import CommandResult, TranscriptMode
from soota.pipeline import doctor as doctor_cmd
from soota.pipeline import estimate as estimate_cmd
from soota.pipeline import ingest as ingest_cmd
from soota.pipeline import inspect as inspect_cmd
from soota.pipeline import list_jobs as list_jobs_cmd
from soota.pipeline import render as render_cmd
from soota.secrets import redact_any

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Soota：给一个链接，搜集内容、补全字幕，留下可追溯 Markdown。",
)
jobs_app = typer.Typer(help="任务列表")
app.add_typer(jobs_app, name="jobs")


def _emit(result: CommandResult, json_output: bool) -> None:
    payload = redact_any(result.model_dump())
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(result.message)
        if result.hint:
            typer.echo(f"hint: {result.hint}", err=True)
        for warning in result.warnings:
            typer.echo(f"warning: {warning}", err=True)
        if result.data.get("output"):
            typer.echo(f"output: {result.data['output']}")
    raise typer.Exit(result.exit_code)


def _fail(exc: SootaError, json_output: bool) -> None:
    payload = redact_any(exc.to_dict())
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(exc.message, err=True)
        if exc.hint:
            typer.echo(f"hint: {exc.hint}", err=True)
    raise typer.Exit(exc.exit_code)


def _run(json_output: bool, fn: Callable[..., CommandResult], *args: Any, **kwargs: Any) -> None:
    try:
        result = fn(*args, **kwargs)
    except SootaError as exc:
        _fail(exc, json_output)
        return
    _emit(result, json_output)


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="stdout 只输出一个 JSON 文档")] = False,
) -> None:
    _run(json_output, doctor_cmd, load_settings())


@app.command()
def inspect(
    url: Annotated[str, typer.Argument(help="YouTube 或 Bilibili URL")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
    offline: Annotated[bool, typer.Option("--offline", help="只识别 URL，不调用 Provider")] = False,
) -> None:
    _run(json_output, inspect_cmd, load_settings(), url, fetch=not offline)


@app.command()
def estimate(
    url: Annotated[str, typer.Argument()],
    mode: Annotated[str, typer.Option("--mode")] = "ingest",
    transcript: Annotated[TranscriptMode, typer.Option("--transcript")] = TranscriptMode.AUTO,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(json_output, estimate_cmd, load_settings(), url, mode=mode, transcript=transcript)


@app.command()
def ingest(
    url: Annotated[str, typer.Argument()],
    transcript: Annotated[TranscriptMode, typer.Option("--transcript")] = TranscriptMode.AUTO,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    max_cost: Annotated[float | None, typer.Option("--max-cost")] = None,
    max_items: Annotated[int | None, typer.Option("--max-items")] = 1,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    if max_items is not None and max_items < 1:
        raise typer.Exit(3)
    _run(
        json_output,
        ingest_cmd,
        load_settings(),
        url,
        transcript=transcript,
        output=output,
        max_cost=max_cost,
        dry_run=dry_run,
        force=force,
    )


@app.command()
def render(
    bundle: Annotated[Path, typer.Option("--bundle", help="manifest.json 或内容包目录")],
    analysis: Annotated[Path, typer.Option("--analysis", help="Analysis JSON")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    _run(json_output, render_cmd, load_settings(), bundle=bundle, analysis=analysis, force=force)


@jobs_app.command("list")
def jobs_list(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(json_output, list_jobs_cmd, load_settings())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
