"""[INPUT]: 已绑定的产品源码与安装清单。
[OUTPUT]: 安装器接口和当前 prefix，供 setup/update 复用。
[POS]: 产品维护与 packaging 的窄桥接；不复制安装事务。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import importlib.util
import sys
from pathlib import Path

from . import runtime


def managed_installation():
    manifest = runtime.runtime_manifest()
    source = runtime.root()
    release = source.parent
    prefix = release.parent.parent
    if release.parent.name != "releases" or manifest["release_id"] != release.name:
        raise RuntimeError("需要由 LoreLab 安装器管理的运行环境。")
    if (prefix / "current").resolve() != release:
        raise RuntimeError("此命令来自旧版本，请重新调用当前安装的 lorelab。")
    return prefix, release


def installer(root: Path | None = None):
    source = root or runtime.root()
    directory = source / "packaging"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("lorelab_packaging_install", directory / "install.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def register(sub):
    setup = sub.add_parser("setup", help="设置知识库、四套 Skill 和命令路径，保留已有配置")
    setup.add_argument("--vault", type=Path)
    setup.add_argument("--subdir")
    setup.add_argument("--mubu-doc")
    setup.add_argument("--mubu-parent", help="幕布父节点 ID；空字符串表示文档根节点")
    setup.add_argument("--mubu-auth", choices=["desktop", "password"])
    setup.add_argument("--skills-dir", type=Path)
    setup.add_argument("--no-skills", action="store_true")
    setup.add_argument("--bin-dir", type=Path)
    setup.add_argument("--no-bin", action="store_true")
    setup.add_argument("--shell-profile", help="auto（默认）、none，或显式 shell 文件路径", default="auto")
    setup.add_argument("--update-feed", help="发布者的 HTTPS 更新清单地址，或本地清单路径")
    setup.add_argument("--non-interactive", action="store_true")
    setup.add_argument("--check-accounts", action="store_true", help="额外只读检查账号；不会登录或写入云端")
    update = sub.add_parser("update", help="整套升级四个 CLI/Skill，保留配置与任务")
    update.add_argument("--from", dest="source", help="可信源码目录；也兼容旧 tar.gz 安装包")
    update.add_argument("--repo", help="明确选择的 Git 仓库；默认沿用首次源码安装记录")
    update.add_argument("--ref", help="仓库分支、标签或提交；默认沿用记录")
    update.add_argument("--sha256", help="远程安装包必需的 SHA256")
    update.add_argument("--feed", help="本次使用的更新清单；默认使用 setup 保存的地址")
    update.add_argument("--check", action="store_true", help="只获取并校验候选源码，不构建或安装")
    update.add_argument("--force", action="store_true", help="相同包也建立新 release，用于修复")


def dispatch(args):
    if args.command == "setup":
        from .setup import setup

        return setup(args)
    from .updates import update

    return update(args)
