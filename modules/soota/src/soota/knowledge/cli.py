"""[INPUT]: 独立或产品转交的知识命令、用户目的地配置。
[OUTPUT]: 文章/学习任务参数与结构化结果；旧命令复用相同解析。
[POS]: Soota 知识 CLI，语义内容仍由外部 Agent 提交。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import argparse
import json
import sys
from pathlib import Path

from . import runtime


def init_arguments(init):
    init.add_argument("--vault", type=Path, required=True)
    init.add_argument("--subdir", required=True)
    init.add_argument("--mubu-doc")
    init.add_argument("--mubu-parent")
    init.add_argument("--mubu-auth", choices=["desktop", "password"], default="desktop")
    init.add_argument("--delete-verified", action="store_true", help="记录当前用户授权的完成后清理策略")
    init.add_argument(
        "--cleanup-after",
        choices=["article", "outline"],
        default="article",
        help="允许清理前必须核对的交付：文章，或文章和幕布",
    )


def register(sub, *, legacy=False):
    if legacy:
        init_arguments(sub.add_parser("init", help="保存知识目的地与清理条件"))
    batch = sub.add_parser("batch" if legacy else "knowledge", help="读取、Agent 交接、写入、核对和清理")
    commands = batch.add_subparsers(dest="action", required=True)
    if not legacy:
        init_arguments(commands.add_parser("init"))
    prepare = commands.add_parser("prepare")
    sources = prepare.add_mutually_exclusive_group(required=True)
    sources.add_argument("--ids-file", type=Path)
    sources.add_argument("--bundles-file", type=Path, help="JSON：已采集 Soota v2 内容包路径数组")
    prepare.add_argument("--vault", type=Path)
    prepare.add_argument("--subdir")
    prepare.add_argument("--mubu-doc")
    prepare.add_argument("--mubu-parent")
    prepare.add_argument("--mubu-auth", choices=["desktop", "password"])
    prepare.add_argument("--delete-verified", action=argparse.BooleanOptionalAction, default=None)
    prepare.add_argument("--cleanup-after", choices=["article", "outline"])
    prepare.add_argument("--with-outline", action="store_true", help="本次明确同时交付幕布；默认只交付文章")
    prepare.add_argument("--state-root", type=Path)
    prepare.add_argument("--source-bundles", type=Path, help="JSON：收藏 ID 到已取得的 Soota 内容包路径")
    submit = commands.add_parser("submit")
    submit.add_argument("job")
    submit.add_argument("--file", type=Path, required=True)
    for name in ["publish", "verify", "status", "cleanup"]:
        cmd = commands.add_parser(name)
        cmd.add_argument("job")
        if name == "cleanup":
            cmd.add_argument("--execute", action="store_true")
    study = sub.add_parser("study", help="从已选文章按需制作复习大纲，不读删 Cubox 收藏")
    study_commands = study.add_subparsers(dest="action", required=True)
    study_prepare = study_commands.add_parser("prepare")
    study_prepare.add_argument("--article", type=Path, action="append", required=True)
    study_prepare.add_argument("--vault", type=Path)
    study_prepare.add_argument("--mubu-doc")
    study_prepare.add_argument("--mubu-parent")
    study_prepare.add_argument("--mubu-auth", choices=["desktop", "password"])
    study_prepare.add_argument("--state-root", type=Path)
    study_submit = study_commands.add_parser("submit")
    study_submit.add_argument("job")
    study_submit.add_argument("--file", type=Path, required=True)
    for name in ["publish", "verify", "status"]:
        study_commands.add_parser(name).add_argument("job")


def parser():
    app = argparse.ArgumentParser(prog="soota", description="内容采集后的知识整理、学习和交付。")
    register(app.add_subparsers(dest="command", required=True))
    return app


def dispatch(args):
    if args.command == "init" or args.command == "knowledge" and args.action == "init":
        vault = args.vault.expanduser().resolve()
        if not vault.is_dir():
            raise ValueError("知识库目录必须已经存在。")
        subdir = Path(args.subdir)
        target = (vault / subdir).resolve()
        if subdir.is_absolute() or not target.is_relative_to(vault) or target == vault:
            raise ValueError("subdir 必须是知识库内的子目录。")
        value = {
            "vault": str(vault),
            "subdir": args.subdir,
            "mubu_doc": args.mubu_doc,
            "mubu_parent": args.mubu_parent,
            "mubu_auth": args.mubu_auth,
            "delete_verified": args.delete_verified,
            "cleanup_after": args.cleanup_after,
        }
        runtime.private_json(runtime.config_path(), value)
        return {"ok": True, "config": str(runtime.config_path()), "settings": value}
    if args.command in {"batch", "knowledge"}:
        from . import workflow

        if args.action == "prepare":
            config = runtime.read_config()
            fields = {}
            for name in ["vault", "subdir", "mubu_doc", "mubu_parent", "delete_verified", "mubu_auth", "cleanup_after"]:
                supplied = getattr(args, name)
                fields[name] = supplied if supplied is not None else config.get(name)
            for name in ["vault", "subdir", *(["mubu_doc"] if args.with_outline else [])]:
                if not fields[name]:
                    raise ValueError(f"缺少 {name}，请传入参数或先执行 soota knowledge init。")
            fields["vault"] = Path(fields["vault"])
            fields["mubu_auth"] = fields["mubu_auth"] or "desktop"
            fields["delete_verified"] = bool(fields["delete_verified"])
            fields["with_outline"] = args.with_outline
            # 旧配置中的删除授权绑定两处核对，不能因升级静默放宽。
            fields["cleanup_after"] = fields["cleanup_after"] or ("outline" if config else "article")
            bundles = json.loads(args.source_bundles.read_text(encoding="utf-8")) if args.source_bundles else None
            return workflow.prepare(
                args.ids_file,
                state_root=args.state_root,
                source_bundles=bundles,
                bundles_file=args.bundles_file,
                **fields,
            )
        if args.action == "submit":
            return workflow.submit(args.job, args.file)
        if args.action == "cleanup":
            return workflow.cleanup(args.job, execute=args.execute)
        return getattr(workflow, args.action)(args.job)
    if args.command == "study":
        from . import study

        if args.action == "prepare":
            config = runtime.read_config()
            fields = {
                name: getattr(args, name) if getattr(args, name) is not None else config.get(name)
                for name in ["vault", "mubu_doc", "mubu_parent", "mubu_auth"]
            }
            for name in ["vault", "mubu_doc"]:
                if not fields[name]:
                    raise ValueError(f"缺少 {name}，请传入参数或先执行 soota knowledge init。")
            fields["vault"] = Path(fields["vault"])
            fields["mubu_auth"] = fields["mubu_auth"] or "desktop"
            return study.prepare(args.article, state_root=args.state_root, **fields)
        if args.action == "submit":
            return study.submit(args.job, args.file)
        return getattr(study, args.action)(args.job)
    raise ValueError("未知命令。")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
