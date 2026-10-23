"""[INPUT]: 已安装组件清单、固定运行时、新旧产品环境变量与 Soota 配置接口。
[OUTPUT]: 显式组件调用、私有 JSON 回执和绑定路径；配置委派给 Soota。
[POS]: LoreLab 分发运行时；LoreHub 使用模块别名，不维护第二份配置或工作流。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path


class ToolError(RuntimeError):
    """组件执行失败；公开错误不复制原始 stderr。"""


def _binding() -> tuple[Path | None, Path | None]:
    """新旧变量必须成组使用；同时存在时两组须完整一致，不交叉补齐。"""
    pairs = []
    for prefix in ("LORELAB", "LOREHUB"):
        pairs.append(tuple(
            Path(value).expanduser().resolve() if (value := os.environ.get(f"{prefix}_{suffix}")) else None
            for suffix in ("ROOT", "RUNTIME_FILE")
        ))
    current, legacy = pairs
    if any(current) and any(legacy) and current != legacy:
        raise ToolError("LORELAB 与 LOREHUB 运行时变量冲突；必须使用同一组 ROOT/RUNTIME_FILE，不能混用。")
    return current if any(current) else legacy


def root() -> Path:
    override, _ = _binding()
    if override:
        path = override
        if not (path / "components.lock.json").is_file():
            raise ToolError("产品 ROOT 缺少组件清单。")
        return path
    for path in Path(__file__).resolve().parents:
        if (path / "components.lock.json").is_file():
            return path
    raise ToolError("找不到产品源码。请使用安装器生成的 lorelab 入口。")


def private_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temp.replace(path)


def runtime_manifest() -> dict:
    _, path = _binding()
    if path is None:
        raise ToolError("尚未使用受管安装。请先运行 install.sh，再使用安装目录下的 lorelab。")
    source = root()
    lock = source / "components.lock.json"
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ToolError("无法读取受管运行时清单；请检查安装。") from exc
    expected = hashlib.sha256(lock.read_bytes()).hexdigest()
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("product") not in ("lorelab", "lorehub")
            or value.get("components_lock_sha256") != expected):
        raise ToolError("运行时与组件清单不一致；请重新构建和安装，不能混用组件版本。")
    # 旧清单仅有锁指纹；新清单额外绑定源码绝对路径，防止同锁不同安装相互调用。
    for field, target in (("source_root", source), ("components_lock", lock)):
        if field in value:
            supplied = value[field]
            if not isinstance(supplied, str) or not Path(supplied).is_absolute() or Path(supplied).resolve() != target:
                raise ToolError("运行时与源码路径绑定不一致；不能混用安装。")
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
    source = root()
    _, manifest = _binding()
    if manifest is None:
        raise ToolError("尚未使用受管安装；不会退回其他组件。")
    # 即使由旧环境变量调用，也让独立 Soota 明确收到同一份受管清单。
    for prefix in ("LORELAB", "LOREHUB"):
        env[f"{prefix}_ROOT"] = str(source)
        env[f"{prefix}_RUNTIME_FILE"] = str(manifest)
    env["SOOTA_KNOWLEDGE_RUNTIME_FILE"] = str(manifest)
    env["SOOTA_KNOWLEDGE_COMPONENTS_LOCK"] = str(source / "components.lock.json")
    env["SOOTA_AUTO_UPDATE"] = "false"
    return env


def run_json(tool: str, args: list[str], receipt: Path | None = None,
             acceptable_codes: tuple[int, ...] = (0,)) -> dict | list | None:
    try:
        result = subprocess.run(tool_command(tool) + args, capture_output=True, text=True,
                                env=tool_environment(), timeout=600, check=False)
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
    from soota.knowledge.runtime import config_path as knowledge_config_path

    return knowledge_config_path()


def read_config() -> dict:
    from soota.knowledge.runtime import read_config as knowledge_read_config

    return knowledge_read_config()
