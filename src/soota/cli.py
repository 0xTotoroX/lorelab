from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from soota.api import platforms as platforms_cmd
from soota.api_cli import app as api_app
from soota.catalog import DEFAULT_MAX_PAGES
from soota.catalog import catalog as catalog_cmd
from soota.catalog import resume_catalog as resume_catalog_cmd
from soota.cli_output import run as _run
from soota.config import load_settings
from soota.models import TranscriptMode
from soota.pipeline import doctor as doctor_cmd
from soota.pipeline import estimate as estimate_cmd
from soota.pipeline import ingest as ingest_cmd
from soota.pipeline import inspect as inspect_cmd
from soota.pipeline import list_jobs as list_jobs_cmd
from soota.pipeline import render as render_cmd

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Soota：给一个链接，搜集内容、补全字幕，留下可追溯 Markdown。",
)
jobs_app = typer.Typer(help="查看任务与续跑目录采集")
app.add_typer(jobs_app, name="jobs")
app.add_typer(api_app, name="api")


@app.command()
def platforms(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(json_output, platforms_cmd)


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
    max_items: Annotated[int, typer.Option("--max-items", help="目录任务的条数上限")] = 100,
    max_pages: Annotated[int, typer.Option("--max-pages", help="目录任务的分页上限")] = DEFAULT_MAX_PAGES,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        json_output,
        estimate_cmd,
        load_settings(),
        url,
        mode=mode,
        transcript=transcript,
        max_items=max_items,
        max_pages=max_pages,
    )


@app.command()
def catalog(
    url: Annotated[str, typer.Argument(help="YouTube 频道或 Bilibili UP 主主页")],
    max_items: Annotated[int, typer.Option("--max-items", help="本任务累计收录的条数上限")] = 100,
    max_pages: Annotated[int, typer.Option("--max-pages", help="本任务累计读取的页数上限")] = DEFAULT_MAX_PAGES,
    max_cost: Annotated[float | None, typer.Option("--max-cost", help="任务累计费用上限，单位 USD；执行时必填")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="离线预估，不联网或创建任务")] = False,
    incremental: Annotated[bool, typer.Option("--incremental", help="跳过已收录条目，整页无新增时停止")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        json_output,
        catalog_cmd,
        load_settings(),
        url,
        max_items=max_items,
        max_pages=max_pages,
        max_cost=max_cost,
        output=output,
        dry_run=dry_run,
        incremental=incremental,
    )


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


@jobs_app.command("resume")
def jobs_resume(
    job_id: Annotated[str, typer.Argument()],
    max_items: Annotated[int | None, typer.Option("--max-items", help="新的累计条数上限")] = None,
    max_pages: Annotated[int | None, typer.Option("--max-pages", help="新的累计页数上限")] = None,
    max_cost: Annotated[float | None, typer.Option("--max-cost", help="新的总费用上限，已有预留不会清零")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _run(
        json_output,
        resume_catalog_cmd,
        load_settings(),
        job_id,
        max_items=max_items,
        max_pages=max_pages,
        max_cost=max_cost,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
