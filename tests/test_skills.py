"""Skill 元数据、实际引用闭包和自有安装来源检查。

运行：PYTHONPATH=src python -m unittest discover -s tests；需 PyYAML 校验 YAML。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from lorelab.components import export_component, refresh

ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "lorelab": Path("skills/lorelab"),
    "cubox": Path("modules/cubox-cli/skills/cubox"),
    "soota": Path("modules/soota/skills/soota"),
    "mubu-integration": Path("modules/mubu-cli"),
}
WORKFLOW = ROOT / "docs/knowledge.md"


def prose(text: str) -> str:
    return re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$", "", text)


def local_links(path: Path):
    path = path.resolve()
    for match in re.finditer(r"\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", prose(path.read_text())):
        link = urlsplit(match.group(1).strip("<>"))
        if not link.scheme and not link.netloc:
            yield (path.parent / unquote(link.path)).resolve() if link.path else path, unquote(link.fragment)


def anchors(path: Path) -> set[str]:
    headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", prose(path.read_text()))
    result = set()
    for heading in headings:
        slug = re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
        unique = slug
        index = 0
        while unique in result:
            index += 1
            unique = f"{slug}-{index}"
        result.add(unique)
    return result


def skill_documents(directory: Path):
    yield directory / "SKILL.md"
    yield from sorted((directory / "references").glob("*.md"))


class SkillTest(unittest.TestCase):
    def assert_local_links(self, paths, boundary: Path, deferred: set[Path] | None = None):
        boundary = boundary.resolve()
        for path in paths:
            for target, anchor in local_links(path):
                with self.subTest(source=str(path), target=str(target), anchor=anchor):
                    self.assertTrue(target.is_relative_to(boundary), "Relative link escapes the source closure")
                    if deferred and target in deferred:
                        continue
                    self.assertTrue(target.exists(), "Relative link target is missing")
                    if anchor and target.suffix == ".md":
                        self.assertIn(anchor, anchors(target), "Relative link heading is missing")

    def test_all_four_skills_have_valid_frontmatter(self):
        allowed = {"name", "description", "license", "allowed-tools", "metadata"}
        for name, relative in SKILLS.items():
            with self.subTest(skill=name):
                text = (ROOT / relative / "SKILL.md").read_text()
                match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
                self.assertIsNotNone(match)
                frontmatter = yaml.safe_load(match.group(1))
                self.assertIsInstance(frontmatter, dict)
                self.assertFalse(set(frontmatter) - allowed)
                self.assertEqual(frontmatter.get("name"), name)
                self.assertRegex(name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertLessEqual(len(name), 64)
                description = frontmatter.get("description")
                self.assertIsInstance(description, str)
                self.assertTrue(description.strip())
                self.assertLessEqual(len(description), 1024)
                self.assertNotRegex(description, r"[<>]")
                self.assertNotIn("[TODO:", text)

    def test_skill_relative_links_and_heading_anchors(self):
        paths = [path for relative in SKILLS.values() for path in skill_documents(ROOT / relative)]
        self.assert_local_links(paths, ROOT)

    def test_workflow_document_links_resolve_after_integration(self):
        links = [target for path in skill_documents(ROOT / SKILLS["lorelab"]) for target, _ in local_links(path)]
        self.assertIn(WORKFLOW, links)
        self.assertTrue(WORKFLOW.is_file())

    def test_component_skill_links_survive_independent_export(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            product = base / "product"
            product.mkdir()
            shutil.copy2(ROOT / "components.lock.json", product)
            shutil.copytree(ROOT / "modules", product / "modules")
            self.assertTrue(refresh(product)["ok"])
            lock = json.loads((product / "components.lock.json").read_text())
            for name, entry in lock["components"].items():
                target = base / name
                export_component(product, name, target)
                skill = Path(entry["skill"]["path"]).relative_to(entry["path"])
                self.assert_local_links(skill_documents(target / skill), target)

    def test_source_installer_uses_included_go_source(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required to exercise the Cubox source installer")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / "component with spaces"
            shutil.copytree(ROOT / "modules/cubox-cli", component)
            hook = root / "observe.cjs"
            hook.write_text('''
const fs = require("fs");
const path = require("path");
require("child_process").execFileSync = (command, args, options) => {
  if (command !== "go" || args[0] !== "build" || args.at(-1) !== ".") throw Error("not a source build");
  if (!fs.existsSync(path.join(options.cwd, "go.mod"))) throw Error("not the included source");
  const output = args[args.indexOf("-o") + 1];
  fs.writeFileSync(output, "synthetic build output");
  fs.writeFileSync(process.env.LOREHUB_TEST_RECEIPT, JSON.stringify({command, args, cwd: options.cwd}));
};
require("child_process").execSync = () => { throw Error("unexpected shell or download"); };
''')
            receipt = root / "receipt.json"
            env = {**os.environ, "LOREHUB_TEST_RECEIPT": str(receipt)}
            subprocess.run([node, "--require", str(hook), str(component / "scripts/install.js")],
                           cwd=root, env=env, check=True, capture_output=True, text=True)
            result = json.loads(receipt.read_text())
            self.assertEqual(Path(result["cwd"]).resolve(), component.resolve())
            binary = "cubox-cli.exe" if os.name == "nt" else "cubox-cli"
            self.assertEqual((component / "bin" / binary).read_text(), "synthetic build output")
            (component / "go.mod").unlink()
            receipt.unlink()
            failed = subprocess.run([node, "--require", str(hook), str(component / "scripts/install.js")],
                                    cwd=root, env=env, capture_output=True, text=True, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(receipt.exists(), "Missing source must not trigger any fallback")

    def test_local_npm_package_contains_build_and_skill_closure(self):
        npm = shutil.which("npm")
        if npm is None:
            self.skipTest("npm is required to check the component source package")
        result = subprocess.run([npm, "pack", "--dry-run", "--ignore-scripts", "--json"],
                                cwd=ROOT / "modules/cubox-cli", capture_output=True, text=True, check=True)
        files = {item["path"] for item in json.loads(result.stdout)[0]["files"]}
        for path in ("go.mod", "go.sum", "main.go", "cmd/root.go", "internal/client/client.go", "Makefile",
                     "scripts/install.js", "scripts/run.js", "skills/cubox/SKILL.md",
                     "skills/cubox/references/card-delete.md", "LICENSE"):
            self.assertIn(path, files)
        self.assertNotIn("bin/cubox-cli", files)


if __name__ == "__main__":
    unittest.main()
