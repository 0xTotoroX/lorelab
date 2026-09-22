from __future__ import annotations

from typing import Annotated, Any

import typer

from soota.cli_output import run
from soota.config import load_settings
from soota.models import CommandResult
from soota.providers.opencli_runtime import OpenCLIRuntime, package_metadata

app = typer.Typer(help="管理独立 OpenCLI 运行时；不会覆盖全局安装。TikHub SDK 通过 uv 锁文件升级。")


def execute(action: str, version: str | None = None) -> CommandResult:
    runtime = OpenCLIRuntime(load_settings())
    data: dict[str, Any]
    if action == "status":
        data = runtime.status()
    elif action == "check-update":
        metadata = package_metadata()
        data = {"current": runtime.status(), "latest": metadata["version"], "engines": metadata.get("engines")}
    elif action == "update":
        assert version is not None
        data = runtime.update(version)
    else:
        data = runtime.rollback()
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message="运行时操作完成。",
        data=data,
        warnings=["这里只检查可执行程序和命令契约；浏览器登录与网站可用性需实际采集验证。"],
    )


@app.command()
def status(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run(json_output, execute, "status")


@app.command("check-update")
def check_update(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run(json_output, execute, "check-update")


@app.command()
def update(
    version: Annotated[str, typer.Option("--version", help="指定完整版本号，隔离安装并验证后启用")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    run(json_output, execute, "update", version)


@app.command()
def rollback(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run(json_output, execute, "rollback")
