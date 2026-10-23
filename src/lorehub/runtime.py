"""[INPUT]: 已安装组件清单、固定运行时和用户环境。
[OUTPUT]: 显式组件调用、私有 JSON 回执和产品路径。
[POS]: 产品入口与工作流共用的进程边界；不调用站点 API。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess


class ToolError(RuntimeError):
    """组件执行失败；公开错误不复制原始 stderr。"""


def root() -> Path:
    override = os.environ.get("LOREHUB_ROOT")
    if override:
        path = Path(override).expanduser().resolve()
        if not (path / "components.lock.json").is_file():
            raise ToolError("LOREHUB_ROOT 缺少组件清单。")
        return path
    for path in Path(__file__).resolve().parents:
        if (path / "components.lock.json").is_file():
            return path
    raise ToolError("找不到产品源码。请使用安装器生成的 lorehub 入口。")


def private_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temp.replace(path)


def runtime_manifest() -> dict:
    override = os.environ.get("LOREHUB_RUNTIME_FILE")
    if not override:
        raise ToolError("尚未使用受管安装。请先运行 install.sh，再使用安装目录下的 lorehub。")
    path = Path(override).expanduser().resolve()
    value = json.loads(path.read_text())
    expected = hashlib.sha256((root() / "components.lock.json").read_bytes()).hexdigest()
    if value.get("schema_version") != 1 or value.get("components_lock_sha256") != expected:
        raise ToolError("运行时与组件清单不一致；请重新构建和安装，不能混用组件版本。")
    return value


def tool_command(tool: str) -> list[str]:
    if tool not in {"cubox", "soota", "mubu"}:
        raise ToolError("未知组件。")
    command = runtime_manifest().get("tools", {}).get(tool)
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise ToolError("受管运行时没有该组件入口。")
    executable = Path(command[0])
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ToolError("受管组件入口不可执行；不会退回 PATH 中的其他版本。")
    return command


def tool_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["SOOTA_AUTO_UPDATE"] = "false"
    return env


def run_json(tool: str, args: list[str], receipt: Path | None = None,
             acceptable_codes: tuple[int, ...] = (0,)) -> dict | list | None:
    try:
        result = subprocess.run(tool_command(tool) + args, capture_output=True, text=True,
                                env=tool_environment(), timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{tool} 超时；若是云端写入，先只读对账，不可直接重发。") from exc
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{tool} 未返回有效 JSON（退出码 {result.returncode}）。") from exc
    if receipt is not None:
        private_json(Path(receipt), value)
    if result.returncode not in acceptable_codes:
        raise ToolError(f"{tool} 执行失败（退出码 {result.returncode}）；请检查私有回执。")
    return value


def forward(tool: str, args: list[str]) -> int:
    return subprocess.call(tool_command(tool) + args, env=tool_environment())


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "lorehub" / "config.json"


def read_config() -> dict:
    path = config_path()
    return json.loads(path.read_text()) if path.is_file() else {}
