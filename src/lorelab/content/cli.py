"""[INPUT]: 明确的内容目标、原文包和旧任务 ID。
[OUTPUT]: LoreLab 内容任务命令；语义由 Agent 提交。
[POS]: content CLI，保留旧 Soota 参数以便迁移。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from soota.artifacts.bundle import bundle_folder
from soota.cli_output import run
from soota.models import CommandResult, TranscriptMode
from soota.platform_support import configure_stdio
from soota.tasks.state import _bundle_lock

from lorelab.content.api import ingest as ingest_cmd
from lorelab.content.api import render as render_cmd
from lorelab.content.api import resume as resume_task_cmd
from lorelab.content.export import _target, export_bundle

app = typer.Typer(add_completion=False, no_args_is_help=True, help="分析、笔记、文章、内容交付与旧任务恢复。")


def run_settings(json_output, fn, *args, **kwargs):
    # Content task execution owns online update checks; offline summaries never check websites.
    from soota.config import load_settings

    run(json_output, lambda: fn(load_settings(), *args, **kwargs))


@app.command()
def ingest(
    url: Annotated[str | None, typer.Argument(help="链接、分享文本、本地文件或内容包")] = None,
    want: Annotated[
        str | None,
        typer.Option(
            "--want",
            help="目标产物，逗号分隔：video/audio/transcript/context/markdown/images/data/analysis/note/outline/article",
        ),
    ] = None,
    optional: Annotated[str | None, typer.Option("--optional", help="可选产物，失败不影响必需目标")] = None,
    inputs_file: Annotated[
        Path | None, typer.Option("--inputs-file", help="链接清单、目录 JSON 或 InputSpec 数组")
    ] = None,
    operation: Annotated[
        str | None, typer.Option("--operation", help="显式原生读取操作，如 opencli.youtube.search")
    ] = None,
    param: Annotated[list[str] | None, typer.Option("--param")] = None,
    params_file: Annotated[Path | None, typer.Option("--params-file")] = None,
    expand: Annotated[bool, typer.Option("--expand", help="把已绑定的搜索结果展开为内容任务")] = False,
    language: Annotated[str | None, typer.Option("--language", help="要求的实际字幕语言")] = None,
    subtitle_formats: Annotated[str, typer.Option("--subtitle-format", help="srt/vtt/txt/json，可逗号组合")] = "srt",
    input_format: Annotated[str | None, typer.Option("--input-format", help="本地字幕 wire 格式")] = None,
    min_height: Annotated[int | None, typer.Option("--min-height", help="视频最低高度，不降清晰度交付")] = None,
    allow_silent: Annotated[bool, typer.Option("--allow-silent", help="允许无音轨的视频")] = False,
    max_bytes: Annotated[int, typer.Option("--max-bytes", help="单个媒体文件字节上限")] = 2 * 1024**3,
    max_pages: Annotated[int, typer.Option("--max-pages")] = 10,
    workers: Annotated[int, typer.Option("--workers", min=1, max=8, help="独立条目并发数；枚举仍有序")] = 1,
    destination: Annotated[Path | None, typer.Option("--destination", help="另外导出到指定目录")] = None,
    vault: Annotated[Path | None, typer.Option("--vault", help="显式 Obsidian Vault 目录")] = None,
    subdir: Annotated[str, typer.Option("--subdir", help="Vault 内目录，不猜测分类")] = "Soota",
    provider: Annotated[
        str | None, typer.Option("--provider", help="auto/opencli/yt-dlp/tikhub/monid/http/local/downie")
    ] = None,
    fallback: Annotated[str | None, typer.Option("--fallback", help="显式允许 tikhub 兜底；仅已验证能力")] = None,
    transcript: Annotated[TranscriptMode, typer.Option("--transcript")] = TranscriptMode.AUTO,
    audio_provider: Annotated[
        str | None, typer.Option("--audio-provider", help="转写用的音频来源：auto/yt-dlp/downie/tikhub/monid")
    ] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    max_cost: Annotated[float | None, typer.Option("--max-cost")] = None,
    max_items: Annotated[int | None, typer.Option("--max-items")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    prefer_youtube: Annotated[
        bool | None,
        typer.Option(
            "--prefer-youtube/--no-prefer-youtube", help="B站视频检查同名YouTube频道及同一期，匹配后优先YouTube字幕"
        ),
    ] = None,
    exclude_promotions: Annotated[
        bool | None,
        typer.Option("--exclude-promotions/--keep-promotions", help="过滤已标注推广；跨平台开关开启时默认启用"),
    ] = None,
    exclude_range: Annotated[
        list[str] | None, typer.Option("--exclude-range", help="人工或Agent核实的推广区间，起秒:止秒，可重复")
    ] = None,
) -> None:
    if max_items is not None and max_items < 1:
        raise typer.Exit(3)
    run_settings(
        json_output,
        ingest_cmd,
        url,
        want=want,
        optional=optional,
        inputs_file=inputs_file,
        operation=operation,
        params=param,
        params_file=params_file,
        expand=expand,
        language=language,
        subtitle_formats=subtitle_formats,
        input_format=input_format,
        min_height=min_height,
        allow_silent=allow_silent,
        max_bytes=max_bytes,
        max_pages=max_pages,
        workers=workers,
        max_items=max_items,
        destination=destination,
        vault=vault,
        subdir=subdir,
        provider=provider,
        fallback=fallback,
        transcript=transcript,
        audio_provider=audio_provider,
        output=output,
        max_cost=max_cost,
        dry_run=dry_run,
        force=force,
        prefer_youtube=prefer_youtube,
        exclude_promotions=exclude_promotions,
        exclude_ranges=exclude_range,
    )


@app.command()
def render(
    bundle: Annotated[Path, typer.Option("--bundle", help="manifest.json 或内容包目录")],
    analysis: Annotated[Path, typer.Option("--analysis", help="Analysis JSON")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    run_settings(json_output, render_cmd, bundle=bundle, analysis=analysis, force=force)


@app.command("resume")
def jobs_resume(
    job_id: Annotated[str, typer.Argument()],
    max_items: Annotated[int | None, typer.Option("--max-items", help="新的累计条数上限")] = None,
    max_pages: Annotated[int | None, typer.Option("--max-pages", help="新的累计页数上限")] = None,
    max_cost: Annotated[float | None, typer.Option("--max-cost", help="新的总费用上限，已有预留不会清零")] = None,
    workers: Annotated[
        int | None, typer.Option("--workers", min=1, max=8, help="覆盖并保存条目并发数；默认沿用任务设置")
    ] = None,
    analysis: Annotated[Path | None, typer.Option("--analysis", help="Agent 提交 JSON，或包含多项提交的目录")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    run_settings(
        json_output,
        resume_task_cmd,
        job_id,
        max_items=max_items,
        max_pages=max_pages,
        max_cost=max_cost,
        workers=workers,
        analysis=analysis,
        force=force,
    )


@app.command("export")
def export_command(
    bundle: Annotated[Path, typer.Option("--bundle")],
    destination: Annotated[Path | None, typer.Option("--destination")] = None,
    vault: Annotated[Path | None, typer.Option("--vault")] = None,
    subdir: Annotated[str, typer.Option("--subdir")] = "Soota",
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    def perform():
        folder = bundle_folder(bundle)
        target = _target(folder, destination, vault, subdir)
        from soota.errors import InputError

        if folder.resolve() == target.resolve():
            raise InputError("导出目标与原内容包相同。")
        with _bundle_lock(folder), _bundle_lock(target):
            result = export_bundle(folder, destination=destination, vault=vault, subdir=subdir)
        return CommandResult(
            ok=True,
            status="success",
            code="ok",
            exit_code=0,
            message="内容包已导出并保留来源链接。",
            data={"export": str(result)},
        )

    run(json_output, perform)


def main(argv=None):
    configure_stdio()
    try:
        result = app(args=argv, prog_name="lorelab content", standalone_mode=True)
        return result if isinstance(result, int) else 0
    except SystemExit as exc:
        return int(exc.code or 0)
