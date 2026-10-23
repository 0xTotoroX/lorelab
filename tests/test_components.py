"""组件维护的内容绑定、路径边界及可独立运行的导出。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lorelab.components import PROVENANCE_FILE, export_component, refresh, verify

REPOSITORY = Path(__file__).resolve().parents[1]


def digest(contents: dict[str, bytes]) -> str:
    files = {path: hashlib.sha256(content).hexdigest() for path, content in contents.items()}
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ComponentsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "product"
        self.component = self.root / "modules/demo"
        self.contents = {
            "main.py": b"from pathlib import Path\nprint(Path('docs/value.txt').read_text().strip())\n",
            "docs/value.txt": b"standalone\n",
            "skills/demo/SKILL.md": b"---\nname: demo\ndescription: Test skill.\n---\n[Guide](references/guide.md)\n",
            "skills/demo/references/guide.md": b"[Build](../../../build.sh)\n",
            "build.sh": b"#!/bin/sh\npython3 main.py\n",
            "pyproject.toml": b'[project]\nname = "demo"\nversion = "1.0.0"\n',
            "LICENSE": b"Synthetic test license\n",
            ".gitignore": b"ignored-source.py\n",
            "ignored-source.py": b"# Still real source, regardless of Git tracking\n",
            "bin/source-helper.py": b"# Source scripts in bin must be included\n",
            ".env.example": b"DEMO_TOKEN=placeholder\n",
            "docs/说明.md": "有效源码使用相对 POSIX 路径。\n".encode(),
        }
        for relative, data in self.contents.items():
            target = self.component / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (self.component / "build.sh").chmod(0o755)
        self.lock = {
            "schema_version": 1,
            "product": {"name": "lorehub", "version": "0.1.0"},
            "components": {"demo": {
                "path": "modules/demo", "repository": "https://example.com/demo.git",
                "revision": "a" * 40, "version": "1.0.0+import",
                "skill": {"name": "demo", "path": "modules/demo/skills/demo"},
                "tree_sha256": digest(self.contents), "extension": {"keep": True},
            }},
        }
        self.write_lock()

    def write_lock(self):
        (self.root / "components.lock.json").write_text(json.dumps(self.lock), encoding="utf-8")

    def test_verify_matches_canonical_relative_file_map(self):
        original = (self.root / "components.lock.json").read_bytes()
        report = verify(self.root)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["components"]["demo"]["tree_sha256"], digest(self.contents))
        self.assertEqual(report["components"]["demo"]["file_count"], len(self.contents))
        self.assertEqual((self.root / "components.lock.json").read_bytes(), original)

    def test_source_skill_build_and_ignored_source_tampering_is_detected(self):
        for relative in ("main.py", "skills/demo/SKILL.md", "skills/demo/references/guide.md",
                         "pyproject.toml", "ignored-source.py", "bin/source-helper.py", ".env.example"):
            with self.subTest(path=relative):
                target = self.component / relative
                original = target.read_bytes()
                target.write_bytes(original + b"\nchanged\n")
                report = verify(self.root)
                self.assertFalse(report["ok"])
                self.assertNotEqual(report["components"]["demo"]["tree_sha256"], digest(self.contents))
                self.assertTrue(report["errors"])
                target.write_bytes(original)

    def test_add_delete_and_rename_change_the_tree(self):
        path = self.component / "new-source.json"
        path.write_text('{}')
        self.assertFalse(verify(self.root)["ok"])
        path.unlink()
        existing = self.component / "docs/value.txt"
        renamed = existing.with_name("renamed.txt")
        existing.rename(renamed)
        self.assertFalse(verify(self.root)["ok"])
        renamed.rename(existing)
        existing.unlink()
        self.assertFalse(verify(self.root)["ok"])

    def test_known_runtime_files_are_neither_hashed_nor_exported(self):
        runtime_files = [
            ".git/config", ".DS_Store", ".venv/lib/private.py", "__pycache__/main.pyc",
            ".pytest_cache/state", ".mypy_cache/state", ".ruff_cache/state", ".cache/data",
            "dist/result.whl", "build/generated.py", "node_modules/package/index.js", ".env",
            ".env.local", ".mubu_token", ".mubu_trash.json", ".coverage", "htmlcov/index.html",
            "output/context.md", "tmp/task.json", ".local/session.json", ".private/review.json",
            "docs/private/plan.md", "PLAN.md", "demo.egg-info/PKG-INFO", "bin/cubox-cli",
        ]
        for relative in runtime_files:
            path = self.component / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic runtime data")
        self.assertTrue(verify(self.root)["ok"])
        target = self.base / "exported"
        export_component(self.root, "demo", target)
        for relative in runtime_files:
            self.assertFalse((target / relative).exists(), relative)
        self.assertTrue((target / ".env.example").is_file())
        self.assertTrue((target / "bin/source-helper.py").is_file())

    def test_refresh_updates_only_tree_hash_and_is_repeatable(self):
        (self.component / "main.py").write_text("print('modified')\n")
        report = refresh(self.root)
        self.assertTrue(report["ok"], report["errors"])
        updated = json.loads((self.root / "components.lock.json").read_text())
        self.assertNotEqual(updated["components"]["demo"]["tree_sha256"], digest(self.contents))
        updated["components"]["demo"]["tree_sha256"] = self.lock["components"]["demo"]["tree_sha256"]
        self.assertEqual(updated, self.lock)
        original = (self.root / "components.lock.json").read_bytes()
        self.assertTrue(refresh(self.root)["ok"])
        self.assertEqual((self.root / "components.lock.json").read_bytes(), original)

    def test_invalid_refresh_does_not_partially_update_lock(self):
        self.lock["components"]["broken"] = {"path": "../outside"}
        self.write_lock()
        before = (self.root / "components.lock.json").read_bytes()
        (self.component / "main.py").write_text("changed")
        report = refresh(self.root)
        self.assertFalse(report["ok"])
        self.assertIn("demo", report["components"])
        self.assertEqual((self.root / "components.lock.json").read_bytes(), before)

    def test_atomic_replace_failure_preserves_old_lock(self):
        (self.component / "main.py").write_text("changed")
        before = (self.root / "components.lock.json").read_bytes()
        with patch("lorelab.components.os.replace", side_effect=OSError("simulated write failure")):
            self.assertFalse(refresh(self.root)["ok"])
        self.assertEqual((self.root / "components.lock.json").read_bytes(), before)
        self.assertEqual(list(self.root.glob(".components.lock.json.*")), [])

    def test_rejects_unsafe_component_and_skill_paths(self):
        for field in ("path", "skill"):
            for value in ("../outside", "/tmp/outside", "modules/../demo", "./modules/demo",
                          "modules//demo", "modules\\demo", "C:/outside", "", ".", "modules/demo\x00"):
                with self.subTest(field=field, path=value):
                    entry = self.lock["components"]["demo"]
                    obj, key = (entry, "path") if field == "path" else (entry["skill"], "path")
                    original = obj[key]
                    obj[key] = value
                    self.write_lock()
                    self.assertFalse(verify(self.root)["ok"])
                    obj[key] = original
        self.lock["components"]["demo"]["skill"]["path"] = "modules"
        self.write_lock()
        self.assertFalse(verify(self.root)["ok"])

    def test_symlink_escape_is_rejected_without_reading_external_content(self):
        outside = self.base / "secret.txt"
        outside.write_text("synthetic external secret")
        for relative in ("leak.txt", "skills/demo/references/leak.txt"):
            with self.subTest(path=relative):
                link = self.component / relative
                link.symlink_to(outside)
                self.assertFalse(verify(self.root)["ok"])
                self.assertFalse(refresh(self.root)["ok"])
                with self.assertRaises(ValueError):
                    export_component(self.root, "demo", self.base / "unsafe")
                self.assertFalse((self.base / "unsafe").exists())
                link.unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.component, target_is_directory=True)
        self.lock["components"]["demo"]["path"] = "alias"
        self.write_lock()
        self.assertFalse(verify(self.root)["ok"])

    def test_missing_or_excluded_skill_is_invalid(self):
        (self.component / "skills/demo/SKILL.md").unlink()
        self.assertFalse(refresh(self.root)["ok"])
        excluded = self.component / "dist/skill"
        excluded.mkdir(parents=True)
        (excluded / "SKILL.md").write_text("hidden")
        self.lock["components"]["demo"]["skill"]["path"] = "modules/demo/dist/skill"
        self.write_lock()
        self.assertFalse(refresh(self.root)["ok"])

    def test_malformed_lock_returns_ok_false(self):
        for value in ("{", "[]", "null", '{"schema_version":true,"components":{}}',
                      '{"schema_version":1,"components":[]}', '{"schema_version":1,"components":{"demo":null}}'):
            with self.subTest(value=value):
                (self.root / "components.lock.json").write_text(value)
                self.assertFalse(verify(self.root)["ok"])
                self.assertFalse(refresh(self.root)["ok"])

    def test_export_isolated_source_build_skill_closure_and_provenance(self):
        target = self.base / "nested/exported"
        report = export_component(self.root, "demo", target)
        self.assertTrue(report["ok"])
        provenance = json.loads((target / PROVENANCE_FILE).read_text())
        self.assertEqual(provenance["recorded_revision"], "a" * 40)
        self.assertEqual(provenance["revision_role"], "import_source")
        self.assertEqual(provenance["tree_sha256"], digest(self.contents))
        self.assertEqual(set(provenance["files"]), set(self.contents))
        self.assertNotIn(str(self.root), json.dumps(provenance))
        self.assertEqual(stat.S_IMODE((target / "build.sh").stat().st_mode), 0o755)
        (self.component / "main.py").write_text("changed after export")
        self.assertEqual((target / "main.py").read_bytes(), self.contents["main.py"])
        (target / "LICENSE").write_text("independent edit")
        self.assertEqual((self.component / "LICENSE").read_bytes(), self.contents["LICENSE"])
        shutil.rmtree(self.root)
        run = subprocess.run([sys.executable, "main.py"], cwd=target, capture_output=True, text=True, check=True)
        self.assertEqual(run.stdout, "standalone\n")
        self.assertTrue((target / provenance["skill"]["path"] / "references/guide.md").is_file())

    def test_export_rejects_stale_lock_existing_targets_and_nested_sources(self):
        for existing in (self.base / "existing-directory", self.base / "existing-file", self.base / "link"):
            if existing.name.endswith("directory"):
                existing.mkdir()
            elif existing.name == "link":
                existing.symlink_to(self.base / "missing")
            else:
                existing.write_text("preserve")
            with self.assertRaises(FileExistsError):
                export_component(self.root, "demo", existing)
            self.assertTrue(os.path.lexists(existing))
        with self.assertRaises(ValueError):
            export_component(self.root, "demo", self.component / "nested")
        with self.assertRaises(ValueError):
            export_component(self.root, "unknown", self.base / "unused")
        (self.component / "main.py").write_text("tampered")
        with self.assertRaises(ValueError):
            export_component(self.root, "demo", self.base / "stale")
        self.assertFalse((self.base / "stale").exists())

    def test_export_detects_mid_copy_mutation_and_removes_partial_destination(self):
        target = self.base / "export"
        original_write = Path.write_bytes

        def change_source(path, content):
            result = original_write(path, content)
            if path.parent == target:
                original_write(self.component / "main.py", b"changed while exporting")
            return result

        with (
            patch.object(Path, "write_bytes", change_source),
            self.assertRaisesRegex(ValueError, "changed during export"),
        ):
            export_component(self.root, "demo", target)
        self.assertFalse(target.exists())

    def test_export_refuses_to_overwrite_source_provenance(self):
        (self.component / PROVENANCE_FILE).write_text("source-owned file")
        self.assertTrue(refresh(self.root)["ok"])
        with self.assertRaisesRegex(ValueError, "reserved export file"):
            export_component(self.root, "demo", self.base / "export")


class ImportedComponentsTest(unittest.TestCase):
    def test_all_real_component_exports_keep_build_and_skill_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            product = base / "product"
            product.mkdir()
            shutil.copy2(REPOSITORY / "components.lock.json", product)
            shutil.copytree(REPOSITORY / "modules", product / "modules")
            self.assertTrue(refresh(product)["ok"])
            lock = json.loads((product / "components.lock.json").read_text())
            needed = {
                "cubox": ["go.mod", "go.sum", "main.go", "Makefile", "package.json", "scripts/install.js"],
                "soota": ["pyproject.toml", "uv.lock", "src/soota/cli.py", "LICENSE"],
                "mubu": ["requirements.txt", "scripts/mubu_api.py", "scripts/mubu/client.py", "LICENSE"],
            }
            for name, paths in needed.items():
                with self.subTest(component=name):
                    target = base / name
                    report = export_component(product, name, target)
                    self.assertTrue(report["ok"])
                    entry = lock["components"][name]
                    skill = Path(entry["skill"]["path"]).relative_to(entry["path"])
                    for path in [*paths, skill / "SKILL.md"]:
                        self.assertTrue((target / path).is_file(), str(path))
                    manifest = json.loads((target / PROVENANCE_FILE).read_text())
                    actual = {path: (target / path).read_bytes() for path in manifest["files"]}
                    self.assertEqual(digest(actual), entry["tree_sha256"])
                    self.assertFalse(any(path.is_symlink() for path in target.rglob("*")))


if __name__ == "__main__":
    unittest.main()
