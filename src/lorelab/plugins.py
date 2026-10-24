"""[INPUT]: 插件目录及当前受管 runtime/bundle。
[OUTPUT]: 四套 Skill 与 CLI 包的版本和完整性匹配结果。
[POS]: 插件分发与本机安装的检查接口，不负责宿主安装或上传。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import hashlib
import json
from pathlib import Path

from . import runtime


def check(root: Path) -> dict:
    root = root.expanduser().resolve()
    errors = []
    try:
        binding = json.loads((root / "lorelab-binding.json").read_text(encoding="utf-8"))
        manifest = runtime.runtime_manifest()
        if binding.get("schema_version") not in {1, 2} or binding.get("product") != "lorelab":
            raise ValueError("无效插件绑定清单")
        expected = {"lorelab", "soota", "cubox", "mubu-integration"}
        if set(binding.get("skills", [])) != expected:
            errors.append("插件未包含四套独立 Skill")
        for name in expected:
            if not (root / "skills" / name / "SKILL.md").is_file():
                errors.append(f"缺少 Skill: {name}")
        if binding["schema_version"] == 2:
            source = runtime.root()
            names = manifest.get("source_files")
            if not isinstance(names, list) or not names:
                raise ValueError("请先从源码仓库更新 CLI，再使用新版 Skill 插件")
            lines = []
            for name in names:
                path = source / name
                if not path.resolve().is_relative_to(source) or not path.is_file():
                    raise ValueError("CLI 源码文件缺失或越界")
                lines.append(f"{name}:{hashlib.sha256(path.read_bytes()).hexdigest()}\n")
            identity = "source-" + hashlib.sha256("".join(lines).encode()).hexdigest()[:16]
            if binding.get("source_fingerprint") != identity:
                errors.append("插件和 CLI 源码版本不一致，请使用同一份仓库版本")
        else:
            installed = json.loads((runtime.root() / "packaging/bundle.json").read_text(encoding="utf-8"))
            if binding.get("bundle_id") != installed.get("release_id"):
                errors.append("旧插件和 CLI 安装包版本不一致")
        if binding.get("components_lock_sha256") != manifest.get("components_lock_sha256"):
            errors.append("插件和 CLI 组件锁不一致")
        files = binding.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("插件没有文件校验清单")
        for name, expected_hash in files.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                errors.append(f"插件文件缺失或越界：{name}")
                continue
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected_hash:
                errors.append(f"插件文件被修改：{name}")
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "root": str(root), "errors": errors,
            "scope": "Skill 与本机 CLI 匹配检查，不代表宿主已加载插件或账号已验证"}
