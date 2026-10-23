"""[INPUT]: 用户命令、受管运行时和产品工作流。
[OUTPUT]: LoreLab CLI 入口及结构化结果。
[POS]: 参数路由层；语义内容由外部 Agent 提交。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__, runtime


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(prog="lorelab", description="把收藏提炼为文章，按需整理学习大纲。")
    app.add_argument("--version", action="version", version=f"LoreLab {__version__}")
    sub = app.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="核对源码、Skill 和受管 CLI，不查询账号")
    tool = sub.add_parser("tool", help="调用当前产品绑定的独立 CLI")
    tool.add_argument("name", choices=["cubox", "soota", "mubu"])
    tool.add_argument("args", nargs=argparse.REMAINDER)
    component = sub.add_parser("components", help="校验、刷新和独立导出组件源码")
    component_sub = component.add_subparsers(dest="action", required=True)
    component_sub.add_parser("verify")
    component_sub.add_parser("refresh")
    export = component_sub.add_parser("export")
    export.add_argument("name", choices=["cubox", "soota", "mubu"])
    export.add_argument("destination", type=Path)
    skills = sub.add_parser("skills", help="查看配套 Skill 入口")
    skills.add_argument("action", choices=["list"])
    from soota.knowledge.cli import register

    register(sub, legacy=True)
    return app


def skill_list() -> list[dict]:
    root = runtime.root()
    manifest = json.loads((root / "components.lock.json").read_text())
    result = [{"name": "lorelab", "path": str(root / "skills/lorelab/SKILL.md")}]
    for entry in manifest["components"].values():
        result.append({"name": entry["skill"]["name"], "path": str(root / entry["skill"]["path"] / "SKILL.md")})
    return result


def doctor() -> dict:
    from .components import verify

    components = verify(runtime.root())
    checks = []
    for name in ["cubox", "soota", "mubu"]:
        try:
            cmd = runtime.tool_command(name)
            result = subprocess.run(
                cmd + ["--help"],
                capture_output=True,
                text=True,
                env=runtime.tool_environment(),
                timeout=30,
                check=False,
            )
            checks.append({"component": name, "ok": result.returncode == 0, "command": cmd})
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            checks.append({"component": name, "ok": False, "error": str(exc)})
    skills = skill_list()
    for entry in skills:
        entry["exists"] = Path(entry["path"]).is_file()
    return {
        "ok": components["ok"] and all(c["ok"] for c in checks) and all(s["exists"] for s in skills),
        "version": __version__,
        "components": components,
        "tools": checks,
        "skills": skills,
        "scope": "本地入口与版本校验，不代表账号或站点可用。",
    }


def dispatch(args: argparse.Namespace) -> object:
    if args.command == "doctor":
        return doctor()
    if args.command == "skills":
        return skill_list()
    if args.command == "components":
        from . import components

        if args.action == "export":
            return components.export_component(runtime.root(), args.name, args.destination)
        return getattr(components, args.action)(runtime.root())
    from soota.knowledge.cli import dispatch as knowledge_dispatch

    return knowledge_dispatch(args)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "tool":
            remainder = args.args[1:] if args.args[:1] == ["--"] else args.args
            return runtime.forward(args.name, remainder)
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
