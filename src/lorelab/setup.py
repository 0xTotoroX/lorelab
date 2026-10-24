"""[INPUT]: 明确设置的目的地、注册路径及已有用户配置。
[OUTPUT]: 合并保存配置、命令/Skill 注册、shell PATH 与只读检查结果。
[POS]: 一次性设置向导；不改任务、不授予删除权限、不处理收藏。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import json
import os
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

from . import maintenance, runtime


def knowledge_settings(args):
    path = runtime.config_path()
    old = runtime.read_config()
    value = dict(old)
    if not args.non_interactive and sys.stdin.isatty():
        if args.vault is None:
            answer = input(f"知识库目录（回车保留或跳过：{old.get('vault', '未配置')}）：").strip()
            if answer:
                args.vault = Path(answer)
        if args.vault is not None and args.subdir is None and not old.get("subdir"):
            args.subdir = input("知识子目录（默认：知识）：").strip() or "知识"
    for key in ("vault", "subdir", "mubu_doc", "mubu_parent", "mubu_auth"):
        supplied = getattr(args, key)
        if supplied is not None:
            if key == "subdir":
                supplied = supplied.replace("\\", "/")
            value[key] = str(supplied.expanduser().resolve()) if key == "vault" else supplied
    if args.mubu_doc is not None and args.mubu_doc != old.get("mubu_doc") and args.mubu_parent is None:
        value.pop("mubu_parent", None)
    if args.vault is not None and not value.get("subdir"):
        value["subdir"] = "知识"
    changed = value != old
    if changed:
        if not value.get("vault") or not value.get("subdir"):
            raise ValueError("请先设置 --vault 和 --subdir；学习目标不代替知识库配置。")
        vault, subdir = Path(value["vault"]), Path(value["subdir"])
        target = (vault / subdir).resolve()
        if not vault.is_dir() or subdir.is_absolute() or target == vault or not target.is_relative_to(vault):
            raise ValueError("知识库须存在，subdir 须是其中的子目录。")
        if not old:
            value.update(delete_verified=False, cleanup_after="article")
    return path, value, changed


def profile_changes(prefix: Path, selection: str) -> dict[Path, bytes]:
    if selection == "none":
        return {}
    if os.name == "nt":
        if selection != "auto":
            raise ValueError("Windows setup 使用用户 PATH；shell-profile 请选择 auto 或 none。")
        entry = str(prefix / "bin").replace("'", "''")
        return {prefix / "env.ps1": f"$env:Path = '{entry};' + $env:Path\n".encode("utf-8-sig")}
    if selection == "auto":
        shell = Path(os.environ.get("SHELL", "")).name
        name = {"zsh": ".zshrc", "bash": ".bash_profile"}.get(shell)
        if not name:
            return {}
        profile = Path.home() / name
    else:
        profile = Path(selection).expanduser().absolute()
    if profile.is_symlink() or profile.exists() and not profile.is_file():
        raise ValueError("shell 配置不是普通文件；请用 --shell-profile none 并手动添加 PATH。")
    before = profile.read_bytes().decode("utf-8") if profile.exists() else ""
    block = ("# >>> LoreLab PATH >>>\n"
             f"[ ! -f {shlex.quote(str(prefix / 'env.sh'))} ] || . {shlex.quote(str(prefix / 'env.sh'))}\n"
             "# <<< LoreLab PATH <<<\n")
    if "# >>> LoreLab PATH >>>" in before and block not in before:
        raise ValueError("已有不同的 LoreLab PATH 配置，保留原内容；请显式选择其他文件或 none。")
    text = before if block in before else before + ("\n" if before and not before.endswith("\n") else "") + block
    return {profile: text.encode(), prefix / "env.sh": f"export PATH={shlex.quote(str(prefix / 'bin'))}:\"$PATH\"\n".encode()}


def write_file(path: Path, content: bytes, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    try:
        pending.write_bytes(content)
        pending.chmod(mode)
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def account_checks(config):
    # auth status 的旧实现网络失败也返回 0；用真正只读的 API 命令验账号。
    commands = {"cubox": ["folder", "list"]}
    if config.get("mubu_doc"):
        commands["mubu"] = ["--agent", "--auth", config.get("mubu_auth") or "desktop", "auth-status"]
    checks = []
    for tool, args in commands.items():
        try:
            result = subprocess.run(runtime.tool_command(tool) + args, env=runtime.tool_environment(),
                                    capture_output=True, timeout=30, check=False)
            checks.append({"component": tool, "ok": result.returncode == 0,
                           "command": ["lorelab", "tool", tool, "--", *args]})
        except (OSError, subprocess.TimeoutExpired):
            checks.append({"component": tool, "ok": False})
    return checks


def setup(args):
    prefix, release = maintenance.managed_installation()
    install = maintenance.installer()
    if args.no_skills and args.skills_dir or args.no_bin and args.bin_dir:
        raise ValueError("no-skills/no-bin 不能与相应目录同时使用。")
    with install.installation_lock(prefix):
        saved = install.settings(prefix)
        skills = None if args.no_skills else args.skills_dir
        bins = None if args.no_bin else args.bin_dir
        if skills is None and not args.no_skills and not saved.get("skills_dirs"):
            skills = Path.home() / ".agents/skills"
        if bins is None and not args.no_bin and not saved.get("bin_dirs"):
            bins = Path.home() / ".local/bin"
        changes = {}
        if args.update_feed:
            from .updates import validate_location

            changes["update_feed"] = validate_location(args.update_feed)
        settings, _ = install.registration(prefix, skills, bins, changes)
        path, value, changed = knowledge_settings(args)
        files = profile_changes(prefix, args.shell_profile)
        if changed:
            files[path] = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        before = {}
        for file in files:
            if file.is_symlink() or file.exists() and not file.is_file():
                raise ValueError(f"拒绝覆盖非普通配置文件：{file}")
            before[file] = (file.read_bytes(), file.stat().st_mode & 0o777) if file.exists() else (None, 0o600)
        written = []
        try:
            for file, content in files.items():
                previous, mode = before[file]
                if content != previous:
                    write_file(file, content, mode)
                    written.append(file)
            from .windows_path import user_path

            with user_path(prefix, args.shell_profile != "none") as windows_path_changed:
                install.activate(prefix, release, skills, bins, changes)
        except BaseException:
            for file in reversed(written):
                content, mode = before[file]
                write_file(file, content, mode) if content is not None else file.unlink()
            raise
    checks = account_checks(value) if args.check_accounts else []
    return {"ok": True, "prefix": str(prefix), "config": str(path), "config_changed": changed,
            "knowledge_configured": bool(value.get("vault") and value.get("subdir")),
            "skills_dirs": settings["skills_dirs"], "bin_dirs": settings["bin_dirs"],
            "files_updated": [str(p) for p in written], "accounts": checks,
            "windows_user_path_updated": windows_path_changed,
            "next": ["lorelab doctor", "lorelab tool cubox -- auth login",
                     "按需配置幕布；安装和配置不代表账号已通过验证。"],
            "shell": (f"重开终端宿主后生效；当前 PowerShell 可执行：. '{str(prefix / 'env.ps1').replace(chr(39), chr(39)*2)}'"
                      if prefix / "env.ps1" in files else
                      f"新终端生效；当前终端可执行：. {shlex.quote(str(prefix / 'env.sh'))}"
                      if prefix / "env.sh" in files else None)}
