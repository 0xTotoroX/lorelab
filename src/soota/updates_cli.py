from __future__ import annotations

from typing import Annotated

import typer

from soota.cli_output import run_settings
from soota.updates import check_updates

app = typer.Typer(help="只读检查三个 Provider 的包版本和上游仓库提交；不安装更新。")


@app.command("check")
def check(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run_settings(json_output, check_updates)
