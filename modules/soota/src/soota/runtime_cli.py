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
    elif action == "connect":
        from soota.providers.opencli_context import connect_runtime

        binary, _ = runtime.resolve()
        with runtime.lock(exclusive=True):
            state = connect_runtime(binary, replace_idle=True)
        data = {"daemon_version": state.get("daemonVersion"), "extension_connected": state.get("extensionConnected")}
    elif action == "check-update":
        metadata = package_metadata()
        data = {"current": runtime.status(), "latest": metadata["version"], "engines": metadata.get("engines")}
    elif action == "update":
        selected_version = version or str(package_metadata()["version"])
        data = runtime.update(selected_version)
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
    version: Annotated[
        str | None, typer.Option("--version", help="省略时查询并安装最新稳定版；验证命令契约后启用")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    run(json_output, execute, "update", version)


@app.command()
def rollback(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run(json_output, execute, "rollback")


@app.command()
def connect(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """启动所选运行时并等待浏览器连接；不重启仍有任务或会话的服务。"""
    run(json_output, execute, "connect")
