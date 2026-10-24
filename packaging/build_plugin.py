#!/usr/bin/env python3
"""[INPUT]: 已验证的 LoreLab 源码仓库与四套 Skill。
[OUTPUT]: 仅含四套独立 Skill、引用文档和源码安装指引的插件 ZIP。
[POS]: 分发格式适配；只从现有 Skill 生成，不维护第二套正文。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import argparse
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SKILLS, sha256, verify_inputs
from repository import fingerprint, provenance

CODE_BLOCKS = re.compile(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$")
LICENSES = [Path("LICENSE"), *(Path("modules") / name / "LICENSE" for name in ("soota", "cubox-cli", "mubu-cli"))]


def is_document(path):
    return path.suffix == ".md" or path.name == "LICENSE"


def mapped(path: Path) -> Path:
    if path == Path("LICENSE"):
        return path
    for name, origin in SKILLS.items():
        if path == Path(origin) or path.is_relative_to(origin):
            return Path("skills") / name / path.relative_to(origin)
    return Path("support") / path


def rewrite_links(text: str, source: Path, target: Path, root: Path) -> str:
    def replace(match):
        raw = match.group(2)
        link = urlsplit(raw.strip("<>"))
        if link.scheme or link.netloc or not link.path:
            return match.group(0)
        original = (root / source.parent / unquote(link.path)).resolve()
        if not original.is_relative_to(root) or not original.exists():
            raise ValueError(f"Skill link escapes bundle or is missing: {source}: {raw}")
        destination = (mapped(original.relative_to(root)) if is_document(original)
                       else Path("RUNTIME.md"))
        relative = os.path.relpath(destination, target.parent).replace(os.sep, "/")
        if not is_document(original):
            relative += "#源码引用"
        elif link.fragment:
            relative += "#" + link.fragment
        return match.group(1) + relative + match.group(3)

    return transform_prose(text, lambda part: re.sub(r"(\[[^\]\n]*\]\()([^\s)]+)(\))", replace, part))


def transform_prose(text, transform):
    # 示例里的 context.md / JOB 等是运行时占位符，不属于插件的文件引用。
    parts, start = [], 0
    for match in CODE_BLOCKS.finditer(text):
        parts.extend([transform(text[start:match.start()]), match.group()])
        start = match.end()
    return "".join([*parts, transform(text[start:])])


def build(root: Path, output_dir: Path) -> Path:
    root = root.resolve()
    verify_inputs(root)
    identity = fingerprint(root)
    origin = provenance(root)
    version = json.loads((root / "components.lock.json").read_text(encoding="utf-8"))["product"]["version"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"lorelab-plugin-{version}-{identity}.zip"
    if output.exists():
        raise ValueError(f"refusing to overwrite plugin: {output}")
    with tempfile.TemporaryDirectory(prefix="lorelab-plugin-") as temporary:
        plugin = Path(temporary) / "lorelab"
        plugin.mkdir()
        # 只走 Skill 的文档引用闭包，不复制 CLI 源码、依赖、安装脚本或运行包。
        pending = [*LICENSES, *(Path(directory) / "SKILL.md" for directory in SKILLS.values())]
        visited = set()
        while pending:
            relative = pending.pop()
            if relative in visited:
                continue
            visited.add(relative)
            source = root / relative
            target = mapped(relative)
            destination = plugin / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            original = source.read_text(encoding="utf-8")
            prose = CODE_BLOCKS.sub("", original)
            for raw in re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", prose):
                link = urlsplit(raw.strip("<>"))
                if link.scheme or link.netloc or not link.path:
                    continue
                referenced = (source.parent / unquote(link.path)).resolve()
                if not referenced.is_relative_to(root) or not referenced.is_file():
                    raise ValueError(f"missing or escaping Skill reference: {relative}: {raw}")
                if is_document(referenced):
                    pending.append(referenced.relative_to(root))
            content = rewrite_links(original, relative, target, root)
            if source.name == "SKILL.md" and relative in [Path(d) / "SKILL.md" for d in SKILLS.values()]:
                parts = content.split("---", 2)
                if len(parts) != 3:
                    raise ValueError(f"missing Skill frontmatter: {source}")
                intro = ("\n\n## 插件运行环境\n\n"
                         "先读取[安装与更新指引](../../RUNTIME.md)。插件不含 CLI；由本地 Agent 从用户指定仓库安装。"
                         "四套 Skill 独立使用，共用 LoreLab 绑定版本。\n")
                content = "---" + parts[1] + "---" + intro + parts[2]
            destination.write_text(content, encoding="utf-8")
        manifest = {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                    "name": "lorelab", "version": version, "description": "采集内容，整理文章，按需制作学习大纲。",
                    "author": {"name": "0xTotoroX"}, "license": "GPL-3.0-only",
                    "extensions": {"com.openai": {"requires_local_executor": True,
                         "onboardingSkill": "./skills/lorelab/SKILL.md",
                         "interface": {"displayName": "LoreLab", "shortDescription": "采集、知识文章与按需学习",
                                       "capabilities": []}}}}
        (plugin / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (plugin / "RUNTIME.md").write_text("""# 本地 Agent 安装与更新

本插件只提供 lorelab、soota、cubox、mubu-integration 四套独立 Skill 及文档。
没有安装包、CLI、Python、Go 或用户凭据。需要可执行本机命令的 Agent。

1. 先运行 `lorelab doctor --plugin-root PLUGIN_ROOT`；PLUGIN_ROOT 替换为本文件所在目录。
2. 缺少 CLI 时，从用户给定的 LoreLab 仓库克隆源码，读取该仓库 `docs/agent-install.md`。
   仓库地址未提供时先取得真实地址，不猜公开地址，不安装原作者的同名产品。
3. macOS 在仓库执行 `sh install.sh --no-skills`；Windows 执行
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1 --no-skills`。
   安装器按本机平台准备工具链并构建四个 CLI。随后运行安装输出中的 setup 命令，带 `--no-skills`。
4. 已有安装使用 `lorelab update --from CHECKOUT`，或沿用记录执行 `lorelab update`。
   CHECKOUT 是用户选择且已检查版本的源码目录；插件版本通过下面的来源指纹核对。
5. 再运行 doctor 和四个 CLI 的帮助检查。账号登录由用户完成；安装不授权云端写入或删除。

插件模式不重复注册全局 Skill，已有配置、任务、账号及其他同名目录保留。
插件更新由宿主管理，CLI 更新由本地 Agent 执行，不能直接改宿主缓存。
版本不符时取得与插件对应的仓库版本，再更新 CLI；不自动降级或混用。

## 源码引用

文档中指向程序实现的链接在此汇总。相关脚本属于已安装 CLI 的 source 目录，
由 `lorelab skills list` 和组件清单定位；插件自身不提供可执行程序。
优先使用四个独立 CLI 或 `lorelab tool`，不把文档中的源码相对路径当作插件内程序。
""", encoding="utf-8")
        (plugin / "RUNTIME.md").write_text((plugin / "RUNTIME.md").read_text(encoding="utf-8") +
            "\n源码内容指纹：`" + identity + "`。\n" +
            ("Git 来源：`" + origin["repository"] + "`，构建时提交：`" + origin["revision"] + "`。\n"
             if origin and "://" in origin["repository"] else
             "发布地址由使用者或维护者提供；本地路径不写入插件。\n"), encoding="utf-8")
        files = {p.relative_to(plugin).as_posix(): sha256(p)
                 for p in sorted(plugin.rglob("*")) if p.is_file()}
        binding = {"schema_version": 2, "product": "lorelab", "version": version,
                   "source_fingerprint": identity, "components_lock_sha256": sha256(root / "components.lock.json"),
                   "skills": sorted(SKILLS), "files": files}
        (plugin / "lorelab-binding.json").write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
        pending = output.with_suffix(".tmp")
        try:
            with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
                for path in sorted(plugin.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(plugin.parent))
            os.replace(pending, output)
        finally:
            pending.unlink(missing_ok=True)
    output.with_name(output.name + ".sha256").write_text(f"{sha256(output)}  {output.name}\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    print(build(args.root, args.output_dir))
