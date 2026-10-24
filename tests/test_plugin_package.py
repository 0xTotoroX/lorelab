"""一个插件中的四个 Skill、相对引用闭包与 CLI 版本绑定。"""

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
import yaml
from test_install import common, fixture_source
from test_skills import local_links

from lorelab import plugins

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import build_plugin


@pytest.mark.parametrize("fence", ["```", "````", "~~~"])
def test_plugin_preserves_runtime_links_in_fenced_examples(tmp_path, fence):
    (tmp_path / "guide.md").write_text("Guide\n", encoding="utf-8")
    prose = "[guide](guide.md)\n"
    example = fence + "markdown\n[context](context.md)\n" + fence + "\n"
    source = Path("SKILL.md")
    target = Path("skills/test/SKILL.md")
    rewritten = build_plugin.rewrite_links(prose + example + prose, source, target, tmp_path)
    assert example in rewritten
    assert rewritten.count("../../support/guide.md") == 2
    assert "context.md" not in build_plugin.CODE_BLOCKS.sub("", prose + example + prose)


def test_plugin_keeps_four_independent_skills_and_version_binding(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    fixture_source(bundle)
    for relative in build_plugin.LICENSES:
        (bundle / relative).write_text("Synthetic copyright and license notice.\n", encoding="utf-8")
    for name, directory in common.SKILLS.items():
        path = bundle / directory / "SKILL.md"
        path.write_text(f"---\nname: {name}\ndescription: Synthetic test workflow\n---\n" + path.read_text())
    common.seal_bundle(bundle)
    # 正式 tar.gz 为可重复归档把时间戳设为 1970；ZIP 最早只支持 1980。
    for path in bundle.rglob("*"):
        if path.is_file():
            os.utime(path, (0, 0))
    archive = build_plugin.build(bundle, tmp_path / "dist")
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(tmp_path / "plugin")
    root = tmp_path / "plugin/lorelab"
    manifest = json.loads((root / "plugin.json").read_text())
    assert manifest["extensions"]["com.openai"]["requires_local_executor"] is True
    assert "skills" not in manifest
    entries = list((root / "skills").glob("*/SKILL.md"))
    assert {p.parent.name for p in entries} == set(common.SKILLS)
    pending, seen = list(entries), set()
    while pending:
        path = pending.pop()
        if path in seen or path.suffix != ".md":
            continue
        seen.add(path)
        for target, _ in local_links(path):
            assert target.is_relative_to(root)
            assert target.exists(), (path, target)
            pending.append(target)
    for entry in entries:
        metadata = yaml.safe_load(entry.read_text().split("---", 2)[1])
        assert metadata["name"] == entry.parent.name
    assert not (root / "runtime.tar.gz").exists()
    assert not (root / "install.sh").exists()
    assert not list(root.rglob("*.py"))
    assert not list(root.rglob("*.whl"))
    assert not list(root.rglob("*.exe"))
    for relative in build_plugin.LICENSES:
        assert (root / build_plugin.mapped(relative)).read_bytes() == (bundle / relative).read_bytes()
    assert "install.ps1" in (root / "RUNTIME.md").read_text()
    monkeypatch.setattr(plugins.runtime, "root", lambda: bundle)
    monkeypatch.setattr(plugins.runtime, "runtime_manifest", lambda: {
        "source_files": common.source_files(bundle),
        "components_lock_sha256": common.sha256(bundle / "components.lock.json")})
    assert plugins.check(root)["ok"]
    (root / "skills/soota/SKILL.md").write_text("changed Skill")
    assert not plugins.check(root)["ok"]
    (bundle / "docs/overview.md").write_text("different CLI build")
    common.seal_bundle(bundle)
    assert any("版本不一致" in error for error in plugins.check(root)["errors"])
