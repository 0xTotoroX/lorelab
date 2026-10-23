"""[INPUT]: 用户命令、受管运行时和产品工作流。
[OUTPUT]: LoreHub CLI 入口及结构化结果。
[POS]: 参数路由层；语义内容由外部 Agent 提交。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from . import __version__
from . import runtime


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(prog="lorehub", description="把收藏提炼为可读知识和大纲。")
    app.add_argument("--version", action="version", version=f"LoreHub {__version__}")
    sub = app.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="核对源码、Skill 和受管 CLI，不查询账号")
    tool = sub.add_parser("tool", help="调用当前产品绑定的独立 CLI")
    tool.add_argument("name", choices=["cubox", "soota", "mubu"])
    tool.add_argument("args", nargs=argparse.REMAINDER)
    init = sub.add_parser("init", help="保存本用户的知识目录和幕布目标")
    init.add_argument("--vault", type=Path, required=True)
    init.add_argument("--subdir", required=True)
    init.add_argument("--mubu-doc", required=True)
    init.add_argument("--mubu-parent")
    init.add_argument("--mubu-auth", choices=["desktop", "password"], default="desktop")
    init.add_argument("--delete-verified", action="store_true", help="记录当前用户授权的完成后清理策略")
    component = sub.add_parser("components", help="校验、刷新和独立导出组件源码")
    component_sub = component.add_subparsers(dest="action", required=True)
    component_sub.add_parser("verify")
    component_sub.add_parser("refresh")
    export = component_sub.add_parser("export")
    export.add_argument("name", choices=["cubox", "soota", "mubu"])
    export.add_argument("destination", type=Path)
    skills = sub.add_parser("skills", help="查看配套 Skill 入口")
    skills.add_argument("action", choices=["list"])
    batch = sub.add_parser("batch", help="读取、Agent 交接、写入、核对和清理")
    commands = batch.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--ids-file", type=Path, required=True)
    prepare.add_argument("--vault", type=Path)
    prepare.add_argument("--subdir")
    prepare.add_argument("--mubu-doc")
    prepare.add_argument("--mubu-parent")
    prepare.add_argument("--mubu-auth", choices=["desktop", "password"])
    prepare.add_argument("--delete-verified", action=argparse.BooleanOptionalAction, default=None)
    prepare.add_argument("--state-root", type=Path)
    submit = commands.add_parser("submit")
    submit.add_argument("job")
    submit.add_argument("--file", type=Path, required=True)
    for name in ["publish", "verify", "status", "cleanup"]:
        cmd = commands.add_parser(name)
        cmd.add_argument("job")
        if name == "cleanup":
            cmd.add_argument("--execute", action="store_true")
    return app


def skill_list() -> list[dict]:
    root = runtime.root()
    manifest = json.loads((root / "components.lock.json").read_text())
    result = [{"name": "lorehub", "path": str(root / "skills/lorehub/SKILL.md")}]
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
            result = subprocess.run(cmd + ["--help"], capture_output=True, text=True,
                                    env=runtime.tool_environment(), timeout=30)
            checks.append({"component": name, "ok": result.returncode == 0, "command": cmd})
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            checks.append({"component": name, "ok": False, "error": str(exc)})
    skills = skill_list()
    for entry in skills:
        entry["exists"] = Path(entry["path"]).is_file()
    return {"ok": components["ok"] and all(c["ok"] for c in checks) and all(s["exists"] for s in skills),
            "version": __version__, "components": components, "tools": checks, "skills": skills,
            "scope": "本地入口与版本校验，不代表账号或站点可用。"}


def dispatch(args: argparse.Namespace) -> object:
    if args.command == "doctor":
        return doctor()
    if args.command == "skills":
        return skill_list()
    if args.command == "init":
        vault = args.vault.expanduser().resolve()
        if not vault.is_dir():
            raise ValueError("知识库目录必须已经存在。")
        subdir = Path(args.subdir)
        target = (vault / subdir).resolve()
        if subdir.is_absolute() or not target.is_relative_to(vault) or target == vault:
            raise ValueError("subdir 必须是知识库内的子目录。")
        value = {"vault": str(vault), "subdir": args.subdir, "mubu_doc": args.mubu_doc,
                 "mubu_parent": args.mubu_parent, "mubu_auth": args.mubu_auth,
                 "delete_verified": args.delete_verified}
        runtime.private_json(runtime.config_path(), value)
        return {"ok": True, "config": str(runtime.config_path()), "settings": value}
    if args.command == "components":
        from . import components
        if args.action == "export":
            return components.export_component(runtime.root(), args.name, args.destination)
        return getattr(components, args.action)(runtime.root())
    if args.command == "batch":
        from . import workflow
        if args.action == "prepare":
            config = runtime.read_config()
            fields = {}
            for name in ["vault", "subdir", "mubu_doc", "mubu_parent", "delete_verified", "mubu_auth"]:
                supplied = getattr(args, name)
                fields[name] = supplied if supplied is not None else config.get(name)
            for name in ["vault", "subdir", "mubu_doc"]:
                if not fields[name]:
                    raise ValueError(f"缺少 {name}，请传入参数或先执行 lorehub init。")
            fields["vault"] = Path(fields["vault"])
            fields["mubu_auth"] = fields["mubu_auth"] or "desktop"
            fields["delete_verified"] = bool(fields["delete_verified"])
            return workflow.prepare(args.ids_file, state_root=args.state_root, **fields)
        if args.action == "submit":
            return workflow.submit(args.job, args.file)
        if args.action == "cleanup":
            return workflow.cleanup(args.job, execute=args.execute)
        return getattr(workflow, args.action)(args.job)
    raise ValueError("未知命令。")


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
