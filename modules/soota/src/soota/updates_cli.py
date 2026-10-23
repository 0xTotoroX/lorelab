from __future__ import annotations

from typing import Annotated

import typer

from soota.cli_output import run_settings
from soota.updates import check_updates

app = typer.Typer(help="检查并更新三个 Provider；MCP 更新不会启用接入。")


@app.command("check")
def check(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run_settings(json_output, check_updates)


@app.command("apply")
def apply(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    from soota.auto_updates import apply_updates

    run_settings(json_output, apply_updates)
