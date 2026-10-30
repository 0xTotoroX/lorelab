"""[INPUT]: 独立 CLI 配置、可选分发器绑定清单和用户环境。
[OUTPUT]: 固定 argv 单次调用、私有 JSON 回执及有界脱敏诊断、兼容知识配置路径。
[POS]: LoreLab 知识流程的组件进程边界与配置兼容。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class ToolError(RuntimeError):
    """组件执行失败；公开错误不复制原始输出。"""


def config_path() -> Path:
    explicit = os.environ.get("LORELAB_CONFIG_FILE") or os.environ.get("SOOTA_KNOWLEDGE_CONFIG_FILE")
    if explicit:
        return Path(explicit).expanduser()
    config_dir = os.environ.get("SOOTA_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser() / "knowledge.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).expanduser()
    canonical = base / "lorelab/config.json"
    for path in [canonical, base / "soota/knowledge.json", base / "lorehub/config.json"]:
        if path.is_file():
            return path
    return canonical


def read_config() -> dict:
    path = config_path()
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(value, dict):
        raise ToolError("知识配置必须是 JSON 对象。")
    return value


def private_json(path: Path, value: object) -> None:
    from .workflow_state import atomic, encoded

    atomic(Path(path), encoded(value))


def _managed() -> dict | None:
    bindings = []
    manifest = os.environ.get("SOOTA_KNOWLEDGE_RUNTIME_FILE")
    lock = os.environ.get("SOOTA_KNOWLEDGE_COMPONENTS_LOCK")
    if manifest or lock:
        if not manifest or not lock:
            raise ToolError("受管知识运行时必须同时指定 runtime 和 components lock。")
        bindings.append((Path(manifest).expanduser().resolve(), Path(lock).expanduser().resolve()))
    for prefix in ("LORELAB", "LOREHUB"):
        manifest, root = os.environ.get(prefix + "_RUNTIME_FILE"), os.environ.get(prefix + "_ROOT")
        if manifest or root:
            if not manifest or not root:
                raise ToolError("受管运行时必须同时指定清单及源码根目录。")
            bindings.append(
                (Path(manifest).expanduser().resolve(), Path(root).expanduser().resolve() / "components.lock.json")
            )
    if not bindings:
        return None
    if len(set(bindings)) != 1:
        raise ToolError("新旧受管运行时配置不一致，不能混用组件版本。")
    manifest, lock = bindings[0]
    value = json.loads(manifest.read_text(encoding="utf-8"))
    expected = hashlib.sha256(lock.read_bytes()).hexdigest()
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("components_lock_sha256") != expected
    ):
        raise ToolError("运行时与组件清单不一致；请重新构建和安装。")
    for field, target in (("components_lock", lock), ("source_root", lock.parent)):
        if field in value:
            supplied = value[field]
            if not isinstance(supplied, str) or not Path(supplied).is_absolute() or Path(supplied).resolve() != target:
                raise ToolError("运行时与源码路径绑定不一致；不能混用安装。")
    return value


def _command(value: object) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x and "\0" not in x for x in value):
        raise ToolError("组件命令必须是非空 JSON argv 数组。")
    executable = Path(value[0])
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ToolError("已指定组件入口不可执行；不会退回 PATH 中的其他版本。")
    return value


def tool_command(tool: str) -> list[str]:
    if tool not in {"cubox", "soota", "mubu", "lorelab"}:
        raise ToolError("未知组件。")
    managed = _managed()
    if tool == "lorelab":
        return _command([sys.executable, "-m", "lorelab.cli"])
    if managed is not None:
        tools = managed.get("tools")
        if not isinstance(tools, dict):
            raise ToolError("受管运行时缺少有效的组件入口表。")
        return _command(tools.get(tool))
    if tool == "soota":
        return _command([sys.executable, "-m", "soota.cli"])
    explicit = os.environ.get(f"LORELAB_{tool.upper()}_COMMAND") or os.environ.get(f"SOOTA_{tool.upper()}_COMMAND")
    if explicit:
        try:
            value = json.loads(explicit)
        except json.JSONDecodeError as exc:
            raise ToolError("组件命令须使用 JSON argv 数组，不接受 shell 文本。") from exc
        return _command(value)
    name = {"cubox": "cubox-cli", "mubu": "mubu-cli"}[tool]
    executable = shutil.which(name)
    if not executable:
        raise ToolError(f"本次需要 {name}；请安装独立 CLI 或设置 LORELAB_{tool.upper()}_COMMAND。")
    return _command([str(Path(executable).absolute())])


def tool_environment() -> dict[str, str]:
    return {**os.environ, "SOOTA_AUTO_UPDATE": "false", "CUBOX_NO_UPDATE_NOTIFIER": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _output_metadata(output: str | bytes | None) -> dict:
    # 未知格式无法可靠逐字段脱敏；只记录类型和大小，不保存正文或摘要哈希。
    if output is None:
        return {"type": "none", "size_bytes": 0}
    if isinstance(output, bytes):
        return {"type": "bytes", "size_bytes": len(output)}
    return {"type": "text", "size_bytes": len(output.encode("utf-8", errors="replace"))}


def _stderr_metadata(output: str | bytes | None) -> dict:
    metadata = _output_metadata(output)
    if output is None:
        return metadata
    # 只检查前 4 KiB；仅允许 CLI 的固定起始包装，不搜索正文或解码 JSON 字段。
    prefix = output[:4096]
    if isinstance(prefix, str):
        prefix = prefix.encode("utf-8", errors="replace")[:4096]
    for wrapper in (b"Error: ", b'{"error":"', b'{\n  "error": "'):
        if prefix.startswith(wrapper):
            prefix = prefix[len(wrapper):]
            break
    match = re.match(rb"(?:HTTP ([1-5][0-9]{2})|API error ([+-]?[0-9]{1,10})):", prefix)
    if match:
        if match[1] is not None:
            metadata["http_status"] = int(match[1])
        else:
            metadata["api_error_code"] = int(match[2])
    return metadata


def _failure_diagnostic(
    receipt: Path | None, failure: str, returncode: int | None, stdout: str | bytes | None, stderr: str | bytes | None
) -> str:
    from .workflow_state import WorkflowError

    if receipt is None:
        return "未指定私有回执路径，未保存诊断。"
    path = Path(receipt).absolute().with_name(Path(receipt).name + ".diagnostic.json")
    diagnostic = {
        "schema_version": 1,
        "failure": failure,
        "returncode": returncode,
        "stdout": _output_metadata(stdout),
        "stderr": _stderr_metadata(stderr),
    }
    try:
        private_json(path, diagnostic)
    except (OSError, WorkflowError):
        # 文件系统错误也可能带私有正文；保留原失败语义，不重发命令。
        return f"私有诊断未能保存，目标位置：{path}。"
    return f"私有诊断：{path}。"


def run_json(tool: str, args: list[str], receipt: Path | None = None, acceptable_codes: tuple[int, ...] = (0,)):
    try:
        result = subprocess.run(
            tool_command(tool) + args, capture_output=True, text=True, encoding="utf-8", env=tool_environment(), timeout=600, check=False
        )
    except subprocess.TimeoutExpired as exc:
        diagnostic = _failure_diagnostic(receipt, "timeout", None, exc.stdout, exc.stderr)
        # TimeoutExpired 的异常链含完整 argv，不能暴露给公开调用方。
        raise ToolError(f"{tool} 超时；{diagnostic}若是云端写入，先只读对账，不可直接重发。") from None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        diagnostic = _failure_diagnostic(receipt, "invalid_json", result.returncode, result.stdout, result.stderr)
        details = _stderr_metadata(result.stderr)
        if "http_status" in details:
            reason = f"HTTP {details['http_status']}；"
        elif "api_error_code" in details:
            reason = f"API error {details['api_error_code']}；"
        else:
            reason = "子命令执行失败；" if result.returncode else ""
        raise ToolError(
            f"{tool} {reason}未返回有效 JSON（退出码 {result.returncode}）；{diagnostic}"
            "若是云端写入，先只读对账，不可直接重发。"
        ) from None
    if receipt is not None:
        private_json(receipt, value)
    if result.returncode not in acceptable_codes:
        raise ToolError(f"{tool} 执行失败（退出码 {result.returncode}）；请检查私有回执。")
    return value
