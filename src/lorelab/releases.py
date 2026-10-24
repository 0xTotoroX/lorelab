"""[INPUT]: 已核对的双包版本、已提交的 LoreLab 和两个发行仓库。
[OUTPUT]: 统一发布预览、Soota 同步、不可覆盖的配对 Git 标签及回执。
[POS]: 发布协调层；跨仓库按顺序提交，允许失败后核对恢复，不声称跨仓库原子性。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from pathlib import Path

from . import component_sync as sync
from .release_versions import versions


def publish(root: Path, *, product_repository: str, soota_repository: str | None = None,
            branch: str = "main", soota_branch: str | None = None, execute: bool = False) -> dict:
    root = root.resolve()
    numbers = versions(root)
    product_repository = sync.repository(product_repository)
    product_tag = "v" + numbers["lorelab"]
    soota_tag = "v" + numbers["soota"]
    with sync.plan(root, target=soota_repository, branch=soota_branch) as prepared:
        if product_repository == prepared.target:
            raise ValueError("LoreLab and standalone Soota must use different repositories")
        source = prepared.source
        branch_ref = sync.ref(prepared.bare, "heads", branch)
        tag_ref = sync.ref(prepared.bare, "tags", product_tag)
        refs = sync.remote_refs(prepared.bare, product_repository, branch_ref, tag_ref)
        if refs.get(branch_ref) != source:
            raise ValueError("publish the reviewed LoreLab source commit to its branch before creating a release")
        product_exists = tag_ref in refs
        if product_exists:
            sync.git(prepared.bare, "fetch", "--no-tags", "--", product_repository, tag_ref)
            if sync.git(prepared.bare, "rev-parse", "FETCH_HEAD^{commit}") != source:
                raise ValueError(f"{product_tag} already names a different LoreLab version; prepare a new version")
        prepared.check_tag(soota_tag)
        # 取回主源对象用于产品 tag；独立仓库中不会出现 LoreLab 的整仓历史。
        sync.git(prepared.bare, "fetch", "--no-tags", "--", product_repository, branch_ref)
        if sync.git(prepared.bare, "rev-parse", "FETCH_HEAD^{commit}") != source:
            raise ValueError("LoreLab branch changed during release preflight")
        result = {"ok": True, "executed": execute, "versions": numbers,
                  "lorelab": {"repository": product_repository, "commit": source, "tag": product_tag},
                  "soota": prepared.report(tag=soota_tag)}
        if execute:
            result["soota"] = prepared.push(tag=soota_tag)
            # 一仓成功、另一仓失败时保留结果；重跑相同源会验证并跳过已有标签。
            if not product_exists:
                sync.git(prepared.bare, "push", "--atomic", "--", product_repository, f"{source}:{tag_ref}")
            actual = sync.remote_refs(prepared.bare, product_repository, tag_ref)
            if actual.get(tag_ref) != refs.get(tag_ref, source):
                raise RuntimeError("LoreLab tag readback differs; inspect the release before retrying")
        return result


def register(sub):
    release = sub.add_parser("release", help="统一准备 Soota/LoreLab 版本及配对发布")
    commands = release.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare", help="更新版本与绑定，不提交或发布")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--version", required=True, help="LoreLab X.Y.Z")
    prepare.add_argument("--soota-version", required=True, help="Soota X.Y.Z")
    publish_command = commands.add_parser("publish", help="预览配对 Git 标签；--execute 才写入两个仓库")
    publish_command.add_argument("--source", type=Path, required=True)
    publish_command.add_argument("--repository", required=True, help="LoreLab 发行仓库")
    publish_command.add_argument("--soota-repository", help="默认使用组件锁中的 Soota 仓库")
    publish_command.add_argument("--branch", default="main")
    publish_command.add_argument("--soota-branch")
    publish_command.add_argument("--execute", action="store_true")


def dispatch(args):
    if args.action == "prepare":
        from .release_versions import prepare

        return prepare(args.source, args.version, args.soota_version)
    return publish(args.source, product_repository=args.repository, soota_repository=args.soota_repository,
                   branch=args.branch, soota_branch=args.soota_branch, execute=args.execute)
