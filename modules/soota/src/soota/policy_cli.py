from __future__ import annotations

import math
from typing import Annotated

import typer

from soota.cli_output import run
from soota.config import PaymentConfig, SootaSettings, load_settings
from soota.errors import InputError
from soota.models import CommandResult
from soota.storage.atomic import atomic_write

app = typer.Typer(help="TikHub 逐次确认 / 自动付费，以及自动暂停的付费余额阈值。")


def policy_result(settings: SootaSettings) -> CommandResult:
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message="当前费用与来源策略。",
        data={"policy": settings.payment.model_dump(), "routing": settings.routing.model_dump()},
    )


def set_policy(settings: SootaSettings, mode: str, min_balance: float | None, no_balance_limit: bool) -> CommandResult:
    if mode not in {"ask", "auto"}:
        raise InputError("--mode 支持 ask 或 auto。")
    if min_balance is not None and (not math.isfinite(min_balance) or min_balance < 0):
        raise InputError("余额阈值必须是有限的非负 USD 金额。")
    if min_balance is not None and no_balance_limit:
        raise InputError("--min-balance 与 --no-balance-limit 不能同时使用。")
    if mode == "auto" and min_balance is None and not no_balance_limit:
        raise InputError("启用自动付费必须明确选择 --min-balance USD 或 --no-balance-limit。")
    policy = PaymentConfig(mode="auto" if mode == "auto" else "ask", min_balance_usd=min_balance)
    atomic_write(settings.config_dir / "payment-policy.json", policy.model_dump_json(indent=2) + "\n")
    return policy_result(settings.model_copy(update={"payment": policy}))


@app.command()
def show(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    run(json_output, lambda: policy_result(load_settings()))


@app.command("set")
def configure(
    mode: Annotated[str, typer.Option("--mode", help="ask：轮到 TikHub 时逐次确认；auto：轮到 TikHub 时自动付费")],
    min_balance: Annotated[
        float | None, typer.Option("--min-balance", help="USD 付费余额，预估扣费后触及此值则暂停")
    ] = None,
    no_balance_limit: Annotated[bool, typer.Option("--no-balance-limit", help="明确不限制剩余余额")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    run(json_output, lambda: set_policy(load_settings(ignore_payment=True), mode, min_balance, no_balance_limit))
