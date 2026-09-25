from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from soota.config import OpenCLIMCPConfig
from soota.errors import ContractError, SourceError
from soota.providers.opencli_runtime import RuntimeUnavailable

VERIFIED_SERVER_VERSION = "0.0.22"


class MCPToolError(SourceError):
    def __init__(self, code: str) -> None:
        self.upstream_code = code
        super().__init__("opencli-mcp 命令失败，未自动重试。", details={"upstream_code": code})


class StdioMCPClient:
    """A bounded, one-call MCP connection owned by this Soota invocation."""

    def __init__(self, config: OpenCLIMCPConfig) -> None:
        self.config = config

    @staticmethod
    def available(config: OpenCLIMCPConfig) -> bool:
        return bool(shutil.which(config.binary or "opencli-mcp"))

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "sites_search":
            raise ContractError("内部客户端仅开放站点发现；站点执行必须经过只读契约检查。")
        return self._call(name, arguments)

    def call_site_readonly(
        self, site: str, command: str, args: dict[str, Any], *, expected_domain: str
    ) -> dict[str, Any]:
        self._assert_no_override(site, command)
        return self._call(
            "site_run",
            {"site": site, "command": command, "args": args},
            readonly_guard=(site, command, args, expected_domain),
        )

    @staticmethod
    def _assert_no_override(site: str, command: str) -> None:
        # The Chrome-owned host loads this directory after built-ins, so a same-name user adapter wins.
        override = Path.home() / ".opencli-mcp" / "adapters" / site / f"{command}.js"
        if override.exists() or override.is_symlink():
            raise ContractError("opencli-mcp 内置只读命令被本地 adapter 覆盖；已拒绝自动调用。")

    @staticmethod
    def _assert_read_contract(
        payload: dict[str, Any], site: str, command: str, args: dict[str, Any], expected_domain: str
    ) -> None:
        results = payload.get("results")
        if not isinstance(results, list):
            raise ContractError("opencli-mcp 未返回站点命令元数据。")
        matches = [
            row for row in results if isinstance(row, dict) and row.get("site") == site and row.get("name") == command
        ]
        if len(matches) != 1 or matches[0].get("access") != "read" or matches[0].get("domain") != expected_domain:
            raise ContractError("opencli-mcp 站点命令不再符合已核验的只读契约。")
        fields = matches[0].get("args")
        if not isinstance(fields, list) or not all(isinstance(field, dict) for field in fields):
            raise ContractError("opencli-mcp 站点参数契约缺失。")
        declared = {field.get("name"): field for field in fields}
        if len(declared) != len(fields) or any(key not in declared for key in args):
            raise ContractError("opencli-mcp 站点参数契约已变化。")
        if any(field.get("required") is True and field.get("name") not in args for field in fields):
            raise ContractError("opencli-mcp 站点新增必填参数。")
        for key, value in args.items():
            expected_type = "int" if isinstance(value, int) and not isinstance(value, bool) else "string"
            if declared[key].get("type") != expected_type:
                raise ContractError("opencli-mcp 站点参数类型已变化。")

    def _call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        readonly_guard: tuple[str, str, dict[str, Any], str] | None = None,
    ) -> dict[str, Any]:
        binary = self.config.binary or "opencli-mcp"
        resolved = shutil.which(binary)
        if resolved is None:
            raise RuntimeUnavailable("opencli-mcp 未安装。", hint="安装并运行 opencli-mcp setup --clients none。")
        try:
            process = subprocess.Popen(
                [resolved, "stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            raise RuntimeUnavailable("opencli-mcp 无法启动。") from exc
        if process.stdin is None or process.stdout is None:
            process.terminate()
            raise RuntimeUnavailable("opencli-mcp 标准输入输出不可用。")
        messages: queue.Queue[bytes] = queue.Queue()
        limit = self.config.max_output_bytes

        def read_stdout() -> None:
            assert process.stdout is not None
            while line := process.stdout.readline(limit + 1):
                messages.put(line)
                if len(line) > limit or not line.endswith(b"\n"):
                    break
            messages.put(b"")

        threading.Thread(target=read_stdout, daemon=True).start()
        try:
            self._send(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "soota", "version": "0.1.0"},
                    },
                },
            )
            initialized = self._response(messages, 1, min(self.config.timeout_seconds, 15))
            handshake = initialized.get("result")
            if not isinstance(handshake, dict):
                raise ContractError("opencli-mcp 初始化契约不匹配。")
            server = handshake.get("serverInfo")
            if not isinstance(server, dict) or server.get("name") != "opencli-mcp":
                raise ContractError("连接的不是已核验的 opencli-mcp 服务。")
            if server.get("version") != VERIFIED_SERVER_VERSION:
                raise ContractError("opencli-mcp 版本尚未经过 Soota 契约核验。")
            self._send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            if readonly_guard is not None:
                site, command, args, expected_domain = readonly_guard
                self._send(
                    process,
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "sites_search",
                            "arguments": {"query": f"{site} {command}", "limit": 100},
                        },
                    },
                )
                discovery = self._decode_tool(self._response(messages, 2, min(self.config.timeout_seconds, 15)))
                self._assert_read_contract(discovery, site, command, args, expected_domain)
                self._assert_no_override(site, command)
            call_id = 3 if readonly_guard is not None else 2
            self._send(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": call_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
                dispatched=True,
            )
            response = self._response(messages, call_id, self.config.timeout_seconds, dispatched=True)
            return self._decode_tool(response)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()

    @staticmethod
    def _decode_tool(response: dict[str, Any]) -> dict[str, Any]:
        result = response.get("result")
        if not isinstance(result, dict):
            raise ContractError("opencli-mcp 工具结果契约不匹配。")
        content = result.get("content")
        if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
            raise ContractError("opencli-mcp 未返回单一文本结果。")
        block = content[0]
        if block.get("type") != "text" or not isinstance(block.get("text"), str):
            raise ContractError("opencli-mcp 文本结果契约不匹配。")
        try:
            payload = json.loads(block["text"])
        except ValueError as exc:
            raise ContractError("opencli-mcp 工具结果不是 JSON。") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            raise ContractError("opencli-mcp 业务结果契约不匹配。")
        if result.get("isError") or not payload["ok"]:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            if not isinstance(code, str):
                raise ContractError("opencli-mcp 错误结果缺少代码。")
            if code in {"host_unavailable", "browser_unavailable", "extension_update_required"}:
                raise RuntimeUnavailable("opencli-mcp 浏览器宿主不可用。")
            raise MCPToolError(code)
        if payload.get("truncated"):
            raise ContractError("opencli-mcp 结果已截断，不能作为完整业务数据。")
        return payload

    @staticmethod
    def _send(process: subprocess.Popen[bytes], message: dict[str, Any], *, dispatched: bool = False) -> None:
        assert process.stdin is not None
        try:
            process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            if dispatched:
                raise SourceError("opencli-mcp 发送请求时连接中断，结果未知；未自动重放或切换来源。") from exc
            raise RuntimeUnavailable("opencli-mcp 连接已断开。") from exc

    def _response(
        self, messages: queue.Queue[bytes], request_id: int, timeout: float, *, dispatched: bool = False
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                if dispatched:
                    raise SourceError("opencli-mcp 请求超时，结果未知；未自动重放或切换来源。") from exc
                raise RuntimeUnavailable("opencli-mcp 初始化超时。") from exc
            if not line:
                if dispatched:
                    raise SourceError("opencli-mcp 连接中断，结果未知；未自动重放或切换来源。")
                raise RuntimeUnavailable("opencli-mcp 初始化前已退出。")
            if len(line) > self.config.max_output_bytes or not line.endswith(b"\n"):
                raise ContractError("opencli-mcp 响应超过大小上限。")
            try:
                response = json.loads(line)
            except ValueError as exc:
                raise ContractError("opencli-mcp 协议响应不是 JSON。") from exc
            if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                raise ContractError("opencli-mcp 协议响应无效。")
            if "id" not in response:
                continue  # Progress and other notifications do not answer this request.
            if response["id"] != request_id:
                raise ContractError("opencli-mcp 响应 ID 不匹配。")
            if "error" in response:
                raise ContractError("opencli-mcp 协议调用失败。")
            return response
