"""[INPUT]: 旧 knowledge/study 命令的原始 argv 与当前安装环境。
[OUTPUT]: 转交 LoreLab 的退出码和输出；不实现工作流或改写任务。
[POS]: Soota 的旧命令兼容边界；普通采集不依赖 LoreLab。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys

from soota.platform_support import utf8_environment


def forward(args: list[str]) -> int:
    if not args or args[0] not in {"knowledge", "study"}:
        raise ValueError("仅兼容旧 knowledge/study 命令。")
    if importlib.util.find_spec("lorelab") is not None:
        command = [sys.executable, "-m", "lorelab.cli"]
    elif any(
        os.environ.get(key)
        for key in (
            "LORELAB_RUNTIME_FILE",
            "LOREHUB_RUNTIME_FILE",
            "SOOTA_KNOWLEDGE_RUNTIME_FILE",
            "LORELAB_ROOT",
            "LOREHUB_ROOT",
            "SOOTA_KNOWLEDGE_COMPONENTS_LOCK",
        )
    ):
        command = None  # 受管安装损坏时不能混用 PATH 上的另一份产品。
    else:
        executable = shutil.which("lorelab")
        command = [executable] if executable else None
    if command is None:
        error = "知识整理与学习流程已迁至 LoreLab。请安装或修复 LoreLab，再用 lorelab knowledge/study 继续原任务。"
        print(json.dumps({"ok": False, "error": error}, ensure_ascii=False), file=sys.stderr)
        return 1
    try:
        result = subprocess.run(
            command + args, capture_output=True, text=True, encoding="utf-8", env=utf8_environment(), check=False
        )
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"无法启动 LoreLab：{exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode
