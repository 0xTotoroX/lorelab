"""Safe OpenCLI diagnostics shared by native reads and standard providers.

[INPUT]: Bounded process results, existing typed errors and redaction helpers.
[OUTPUT]: Safe errors with known upstream codes, reasons and recovery hints.
[POS]: providers diagnostic boundary; never retries or publishes raw output.
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import json
import re

from soota.errors import (
    AuthBudgetError,
    CaptionsAbsent,
    CaptionUnavailable,
    ContractError,
    InputError,
    SootaError,
    SourceError,
)
from soota.providers.opencli_runtime import RuntimeUnavailable
from soota.providers.process import ProcessResult
from soota.secrets import redact_any

# Do not echo arbitrary upstream codes, messages, hints, causes or trace paths.
UPSTREAM_CODES = {
    "ARGUMENT",
    "AUTH_REQUIRED",
    "BROWSER_CONNECT",
    "COMMAND_EXEC",
    "CONFIG",
    "EMPTY_RESULT",
    "LOGIN_WALL",
    "TIMEOUT",
    "UNKNOWN",
    "SECURITY_BLOCK",
    "RATE_LIMIT",
    "RATE_LIMITED",
    "FORBIDDEN",
    "PERMISSION_DENIED",
    "INVALID_ARGUMENT",
    "NETWORK_ERROR",
    "NAVIGATION_ERROR",
}
LAYOUT_REASONS = (
    "ambiguous_option",
    "option_not_found",
    "ambiguous_group",
    "group_not_found",
    "ambiguous_filter_panel",
    "ambiguous_filter_trigger",
    "filter_panel_not_found",
)


def failure(result: ProcessResult, *, operation: str, read_only: bool) -> SootaError:
    """Classify upstream output without publishing any upstream free text."""
    code = None
    messages: list[str] = []
    for output in (result.stderr, result.stdout):
        try:
            payload = json.loads(output)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            candidate = payload["error"].get("code")
            primary = payload["error"].get("message")
            messages.append(primary if isinstance(primary, str) else "")
        else:
            match = re.search(r"(?m)^\s*code:\s*['\"]?([A-Z_]+)\b", output)
            candidate = match[1] if match else None
            primary_line = re.search(r"(?m)^\s*message:\s*(.+)$", output)
            messages.append(primary_line[1] if primary_line else output)
        if isinstance(candidate, str) and candidate in UPSTREAM_CODES:
            code = code or candidate
    message = "\n".join(messages).lower()
    details: dict[str, object] = {
        "exit_code": result.returncode,
        "upstream_code": code or "UNKNOWN",
        "attempts": 1,
    }

    def error(
        kind: type[SootaError], category: str, reason: str, text: str, hint: str, *, transient: bool = False
    ) -> SootaError:
        return kind(
            text,
            hint=hint,
            details=redact_any(
                {
                    **details,
                    "category": category,
                    "reason": reason,
                    "retryable": transient and read_only,
                }
            ),
        )

    if "creating browser windows from extensions is not supported in owl." in message:
        return error(
            RuntimeUnavailable,
            "unavailable",
            "browser_surface_unsupported",
            "OpenCLI 当前浏览器不支持创建窗口。",
            "连接受支持的 Google Chrome Browser Bridge，并通过 OPENCLI_PROFILE 选择其 context 后再恢复任务。",
        )
    if code in {"RATE_LIMIT", "RATE_LIMITED", "SECURITY_BLOCK"} or any(
        token in message
        for token in ("429", "rate_limit", "rate limit", "too many requests", "captcha", "security_block")
    ):
        return error(
            AuthBudgetError,
            "rate_limit",
            "access_throttled",
            "OpenCLI 遇到限流或安全验证。",
            "停止重放；按站点提示等待或由用户完成验证后，再显式恢复任务。",
        )
    if code in {"AUTH_REQUIRED", "LOGIN_WALL"} or any(
        token in message for token in ("login_required", "auth_required", "unauthorized", "not logged in", "login_wall")
    ):
        return error(
            AuthBudgetError,
            "auth",
            "login_required",
            "OpenCLI 需要有效的网站登录状态。",
            "由用户检查所选浏览器账号与登录状态，处理后再显式恢复任务。",
        )
    if result.returncode == 77 or code in {"FORBIDDEN", "PERMISSION_DENIED"} or "forbidden" in message:
        return error(
            AuthBudgetError,
            "permission",
            "access_denied",
            "OpenCLI 访问权限不足。",
            "确认当前账号有权读取该内容；未解决权限前不要重放。",
        )
    if code in {"ARGUMENT", "INVALID_ARGUMENT", "CONFIG"} or result.returncode in {2, 78}:
        return error(
            InputError,
            "input",
            "invalid_arguments",
            "OpenCLI 参数或配置不符合要求。",
            "用 features show 核对参数和运行时配置；更正输入后创建新任务。",
        )
    layout = next((reason for reason in LAYOUT_REASONS if reason in message), None)
    if layout or "filter layout" in message or "chip_not_active" in message:
        return error(
            ContractError,
            "contract",
            layout or "filter_not_applied",
            "OpenCLI 页面筛选契约不匹配。",
            "检查受管兼容补丁与实际筛选状态；不得跳过筛选或把未筛选结果当成功。",
        )
    if code == "EMPTY_RESULT" and operation in {"bilibili/subtitle", "youtube/transcript"}:
        if operation == "bilibili/subtitle" and "此视频没有发现外挂或智能字幕。" in result.stderr:
            return error(
                CaptionsAbsent,
                "captions",
                "empty_track_list",
                "B 站已返回空字幕轨道列表。",
                "auto 可继续音频转写；captions-only 在此结束。",
            )
        return error(
            CaptionUnavailable,
            "captions",
            "empty_response",
            "OpenCLI 返回空字幕结果，但尚不能确认视频没有字幕轨道。",
            "保留未知状态，按已有字幕来源策略处理。",
        )
    if operation == "youtube/transcript" and "caption url returned empty response" in message:
        return error(
            CaptionUnavailable,
            "captions",
            "empty_response",
            "OpenCLI 字幕地址返回空响应，采集未完成。",
            "auto 模式可继续 yt-dlp 免费兜底；付费来源仍受费用策略控制。",
        )
    if code == "BROWSER_CONNECT" and any(t in message for t in ("extension not connected", "daemon not running")):
        return error(
            RuntimeUnavailable,
            "unavailable",
            "bridge_unavailable",
            "OpenCLI Browser Bridge 不可用。",
            "检查 Chrome 和 Browser Bridge 扩展连接，连接恢复后再显式恢复任务。",
        )
    if code == "NAVIGATION_ERROR" or "navigation rejected" in message:
        return error(
            SourceError,
            "transient",
            "navigation_rejected",
            "OpenCLI 浏览器导航被拒绝，采集未完成。",
            "检查页面与 Bridge 状态；只读任务可稍后 jobs resume，写操作先核对实际结果。",
            transient=True,
        )
    if (
        code in {"TIMEOUT", "NETWORK_ERROR"}
        or result.returncode == 75
        or any(token in message for token in ("timed out", "net::err_", "econnreset", "econnrefused", "fetch failed"))
    ):
        return error(
            SourceError,
            "transient",
            "timeout" if code == "TIMEOUT" or result.returncode == 75 or "timed out" in message else "network_error",
            "OpenCLI 暂时网络或页面等待失败。",
            "只读任务可稍后 jobs resume；未自动重试。写操作须先核对是否已执行。",
            transient=True,
        )
    return error(
        SourceError,
        "unknown",
        "upstream_failure",
        "OpenCLI 执行失败；结果尚不明确，未自动重试。",
        "检查实际页面与操作状态后再决定是否恢复；不根据退出码盲目重放。",
    )


def process_failure(exc: SourceError, *, read_only: bool) -> SourceError:
    """Local subprocess limits have no known upstream exit status."""
    reason = exc.details.get("reason")
    if reason not in {"timeout", "output_limit"}:
        return exc
    return SourceError(
        "OpenCLI 调用超时。" if reason == "timeout" else "OpenCLI 输出超过上限。",
        hint="未自动重试；只读超时可稍后 jobs resume，其他情况须先检查实际结果和限制。",
        details={
            "category": "transient" if reason == "timeout" else "contract",
            "reason": reason,
            "retryable": reason == "timeout" and read_only,
            "exit_code": None,
            "attempts": 1,
        },
    )


def invalid_json() -> ContractError:
    return ContractError(
        "OpenCLI 没有返回有效 JSON；操作可能已执行，请先核对状态。",
        hint="不要把格式失败当作空结果；核对运行时契约及实际操作结果后再决定是否恢复。",
        details={"category": "contract", "reason": "invalid_json", "retryable": False, "exit_code": 0, "attempts": 1},
    )
