#!/usr/bin/env python3
"""[INPUT]: 已验证的 LoreLab 完整发行 bundle。
[OUTPUT]: 含四套独立 Skill 与同版安装包的本地插件 ZIP。
[POS]: 分发格式适配；只从现有 Skill 生成，不维护第二套正文。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SKILLS, copy_source, sha256, verify_bundle


def mapped(path: Path) -> Path:
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
        destination = mapped(original.relative_to(root))
        relative = os.path.relpath(destination, target.parent)
        if link.fragment:
            relative += "#" + link.fragment
        return match.group(1) + relative + match.group(3)

    return re.sub(r"(\[[^\]\n]*\]\()([^\s)]+)(\))", replace, text)


def build(root: Path, output_dir: Path) -> Path:
    root = root.resolve()
    bundle = verify_bundle(root)
    version = json.loads((root / "components.lock.json").read_text())["product"]["version"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"lorelab-plugin-{bundle['release_id']}.zip"
    if output.exists():
        raise ValueError(f"refusing to overwrite plugin: {output}")
    with tempfile.TemporaryDirectory(prefix="lorelab-plugin-") as temporary:
        plugin = Path(temporary) / "lorelab"
        # ZIP 解包器不一定保留可执行位。运行包以 tar.gz 嵌入，安装时按原模式展开。
        files = [name for name in bundle["files"]
                 if not name.startswith(("packaging/wheels/", "packaging/prebuilt/"))]
        copy_source(root, plugin / "support", files)
        with tarfile.open(plugin / "runtime.tar.gz", "w:gz") as archive:
            for name in [*bundle["files"], "packaging/bundle.json"]:
                archive.add(root / name, arcname="bundle/" + name, recursive=False)
        (plugin / "install.sh").write_text('''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/lorelab-plugin.XXXXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
tar -xzf "$root/runtime.tar.gz" -C "$work"
sh "$work/bundle/install.sh" "$@"
''')
        for directory in SKILLS.values():
            for source in sorted((root / directory).rglob("*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(root)
                target = mapped(relative)
                destination = plugin / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix == ".md":
                    content = rewrite_links(source.read_text(), relative, target, root)
                    if source == root / directory / "SKILL.md":
                        parts = content.split("---", 2)
                        if len(parts) != 3:
                            raise ValueError(f"missing Skill frontmatter: {source}")
                        intro = ("\n\n## 插件运行环境\n\n"
                                 "先读取本插件的[运行环境约定](../../RUNTIME.md)，按其中的命令核对配套 CLI。"
                                 "四套 Skill 独立使用，共用同一版 LoreLab 运行环境。\n")
                        content = "---" + parts[1] + "---" + intro + parts[2]
                    destination.write_text(content)
                else:
                    shutil.copy2(source, destination)
        manifest = {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                    "name": "lorelab", "version": version, "description": "采集内容，整理文章，按需制作学习大纲。",
                    "author": {"name": "0xTotoroX"}, "license": "GPL-3.0-only",
                    "extensions": {"com.openai": {"requires_local_executor": True,
                         "onboardingSkill": "./skills/lorelab/SKILL.md",
                         "interface": {"displayName": "LoreLab", "shortDescription": "采集、知识文章与按需学习",
                                       "capabilities": []}}}}
        (plugin / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        (plugin / "RUNTIME.md").write_text("""# 配套运行环境

本插件保留 lorelab、soota、cubox、mubu-integration 四套独立 Skill，CLI 在本机执行。
仅支持 macOS Apple Silicon；安卓手机不能直接运行这个安装包。

以下 PLUGIN_ROOT 指本文件所在插件目录。执行时替换为实际绝对路径，不假定同名环境变量存在。
先运行 `lorelab doctor --plugin-root PLUGIN_ROOT`。缺少 CLI 时，使用配套安装器：

```sh
sh PLUGIN_ROOT/install.sh --no-skills
"$HOME/.local/share/lorelab/bin/lorelab" setup --no-skills
```

插件已向宿主提供四套 Skill，安装器不再新建全局 Skill 注册。已有外部 Skill 不自动移除。
已有安装的 doctor 报版本不符时，核对用户要采用的版本；不要静默降级 CLI 或混用 Skill。
需要采用此插件配套版本时，使用 `lorelab update --from PLUGIN_ROOT/runtime.tar.gz` 后重新检查。
安装与账号登录是两步；由 setup 引导目的地配置，按实际任务检查对应账号，不执行云端写入。
升级插件时保持其 CLI 包同版；宿主更新插件不会自动更新本机 CLI，doctor 会检测不匹配。
""")
        files = {p.relative_to(plugin).as_posix(): sha256(p)
                 for p in sorted(plugin.rglob("*")) if p.is_file()}
        binding = {"schema_version": 1, "product": "lorelab", "version": version,
                   "bundle_id": bundle["release_id"], "components_lock_sha256": sha256(root / "components.lock.json"),
                   "skills": sorted(SKILLS), "files": files}
        (plugin / "lorelab-binding.json").write_text(json.dumps(binding, indent=2) + "\n")
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
    parser.add_argument("--bundle", required=True, type=Path, help="完整 tar.gz 或已解压的 bundle 目录")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lorelab.updates import unpack

    with unpack(args.bundle.expanduser().resolve()) as root:
        print(build(root, args.output_dir.expanduser().resolve()))
