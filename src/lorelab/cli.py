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
    sub.add_parser("content", help="分析、笔记、文章、内容交付与旧任务恢复", add_help=False)
    check = sub.add_parser("doctor", help="核对源码、Skill 和受管 CLI，不查询账号")
    check.add_argument("--plugin-root", type=Path, help="额外核对插件包与当前 CLI 同版")
    tool = sub.add_parser("tool", help="调用当前产品绑定的独立 CLI")
    tool.add_argument("name", choices=["cubox", "soota", "mubu"])
    tool.add_argument("args", nargs=argparse.REMAINDER)
    component = sub.add_parser("components", help="校验、导出组件和同步独立 Soota 仓库")
    component_sub = component.add_subparsers(dest="action", required=True)
    for action in ("verify", "refresh"):
        command = component_sub.add_parser(action)
        command.add_argument("--source", type=Path, help="指定开发主源；省略则使用当前绑定源码")
    export = component_sub.add_parser("export")
    export.add_argument("name", choices=["cubox", "soota", "mubu"])
    export.add_argument("destination", type=Path)
    export.add_argument("--source", type=Path, help="指定开发主源，保留默认受管导出行为")
    sync = component_sub.add_parser("sync", help="预览 Soota 单向同步；--execute 才写入目标仓库")
    sync.add_argument("name", choices=["soota"])
    sync.add_argument("--source", type=Path, required=True, help="唯一开发源 LoreLab checkout")
    sync.add_argument("--repository", help="默认使用组件锁中的独立仓库")
    sync.add_argument("--branch")
    sync.add_argument("--execute", action="store_true")
    skills = sub.add_parser("skills", help="查看配套 Skill 入口")
    skills.add_argument("action", choices=["list"])
    from .maintenance import register as maintenance_register

    maintenance_register(sub)
    from .releases import register as release_register

    release_register(sub)
    from lorelab.knowledge.cli import register

    register(sub)
    return app


def skill_list() -> list[dict]:
    root = runtime.root()
    manifest = json.loads((root / "components.lock.json").read_text(encoding="utf-8"))
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
                encoding="utf-8",
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
    if args.command == "release":
        from .releases import dispatch as release_dispatch

        return release_dispatch(args)
    if args.command in {"setup", "update"}:
        from .maintenance import dispatch as maintenance_dispatch

        return maintenance_dispatch(args)
    if args.command == "doctor":
        result = doctor()
        if args.plugin_root:
            from .plugins import check

            result["plugin"] = check(args.plugin_root)
            result["ok"] = result["ok"] and result["plugin"]["ok"]
        return result
    if args.command == "skills":
        return skill_list()
    if args.command == "components":
        from . import components

        if args.action == "sync":
            from .component_sync import synchronize

            return synchronize(args.source, target=args.repository, branch=args.branch, execute=args.execute)
        if args.action == "export":
            return components.export_component(args.source or runtime.root(), args.name, args.destination)
        return getattr(components, args.action)(args.source or runtime.root())
    from lorelab.knowledge.cli import dispatch as knowledge_dispatch

    return knowledge_dispatch(args)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["content"]:
        from .content.cli import main as content_main

        return content_main(argv[1:])
    args = parser().parse_args(argv)
    try:
        if args.command == "tool":
            remainder = args.args[1:] if args.args[:1] == ["--"] else args.args
            return runtime.forward(args.name, remainder)
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
