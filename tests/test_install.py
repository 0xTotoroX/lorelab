"""安装事务和入口契约：外部下载替换为小型本地运行环境。"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
sys.path.insert(0, str(PACKAGING))
import common

spec = importlib.util.spec_from_file_location("lorehub_installer", PACKAGING / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def put(root, name, value, executable=False):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    if executable:
        path.chmod(0o755)
    return path


def fixture_source(root):
    put(root, "NOTICE.md", "Synthetic license notice\n")
    put(root, "uv.lock", "# source test lock\n")
    put(root, "docs/overview.md", "[Licenses](../NOTICE.md)\n")
    put(root, "src/lorehub/__init__.py", "")
    put(root, "src/lorehub/cli.py", """import json, os, sys
if __name__ == '__main__':
    print(json.dumps({'root': os.environ['LOREHUB_ROOT'],
        'runtime': os.environ['LOREHUB_RUNTIME_FILE'], 'args': sys.argv[1:],
        'auto_update': os.environ['SOOTA_AUTO_UPDATE']}))
""")
    put(root, "src/lorehub/components.py", """import hashlib, json
def verify(root):
    expected = json.loads((root / 'components.lock.json').read_text())['test_sha256']
    actual = hashlib.sha256((root / 'modules/cubox-cli/main.go').read_bytes()).hexdigest()
    return {'ok': expected == actual}
""")
    code = put(root, "modules/cubox-cli/main.go", "package main\n")
    common.write_json(root / "components.lock.json", {"schema_version": 1,
        "product": {"version": "0.1.0"}, "test_sha256": common.sha256(code)})
    for path in common.SKILLS.values():
        put(root, f"{path}/SKILL.md", "[Guide](docs/guide.md) and [entry](scripts/entry.py)\n")
        put(root, f"{path}/docs/guide.md", "[More](../references/more.md)\n")
        put(root, f"{path}/references/more.md", "Complete guide\n")
        put(root, f"{path}/scripts/entry.py", "# helper\n")
    with (root / "skills/lorehub/SKILL.md").open("a") as stream:
        stream.write("[Product overview](../../docs/overview.md)\n")
    put(root, "modules/mubu-cli/scripts/mubu_api.py", "import json,sys; print(json.dumps(sys.argv))\n")
    put(root, "packaging/requirements.lock", "")
    put(root, "packaging/build-requirements.lock", "")
    put(root, "packaging/prebuilt/cubox-cli", "#!/bin/sh\nprintf 'bundled cubox\\n'\n", True)
    put(root, "packaging/wheels/fixture.whl", "fixture only")
    common.seal_bundle(root)


def fixture_environment(release, uv):
    venv.EnvBuilder(with_pip=False, symlinks=True).create(release / "venv")
    site = next((release / "venv/lib").glob("python*/site-packages"))
    (site / "fixture.pth").write_text(str(release / "source/src") + "\n")
    put(release, "venv/bin/soota", "#!/bin/sh\nprintf 'bundled soota\\n'\n", True)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lorehub tests '")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "bundle with spaces"
        fixture_source(self.source)
        self.prefix = self.base / "installed product's files"
        self.skills = self.base / "agent skills"

    @contextlib.contextmanager
    def local_dependencies(self):
        with patch.object(installer, "get_uv", return_value=Path("/unused/uv")), \
             patch.object(installer, "install_environment", side_effect=fixture_environment):
            yield

    def install(self, skills=True):
        with self.local_dependencies():
            return installer.install(self.source, self.prefix, self.skills if skills else None)

    def assert_skill_closure(self, release):
        boundary = (release / "source").resolve()
        pending = [self.skills / name / "SKILL.md" for name in common.SKILLS]
        seen = set()
        while pending:
            path = pending.pop().resolve()
            self.assertTrue(path.is_relative_to(boundary), str(path))
            self.assertTrue(path.is_file(), f"missing installed Skill reference: {path}")
            if path in seen or path.suffix != ".md":
                continue
            seen.add(path)
            text = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$", "", path.read_text())
            for raw in re.findall(r"\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text):
                link = urlsplit(raw.strip("<>"))
                if not link.scheme and not link.netloc and link.path:
                    pending.append(path.parent / unquote(link.path))

    def test_install_runs_from_paths_with_spaces_and_keeps_full_skills(self):
        release = self.install()
        self.assertEqual((self.prefix / "current").resolve(), release)
        runtime = json.loads((release / "runtime.json").read_text())
        self.assertEqual(runtime["schema_version"], 1)
        self.assertEqual(runtime["release_id"], release.name)
        self.assertEqual(runtime["components_lock_sha256"], common.sha256(release / "source/components.lock.json"))
        self.assertEqual(runtime["tools"]["mubu"][1], str(release / "source/modules/mubu-cli/scripts/mubu_api.py"))
        for name in common.SKILLS:
            self.assertTrue((self.skills / name / "docs/guide.md").is_file())
            self.assertTrue((self.skills / name / "scripts/entry.py").is_file())
        self.assert_skill_closure(release)
        self.assertTrue((release / "source/NOTICE.md").is_file())
        self.assertTrue((release / "source/uv.lock").is_file())
        output = subprocess.check_output([self.prefix / "bin/lorehub", "two words", "$(touch nope)"], text=True)
        data = json.loads(output)
        self.assertEqual(data["root"], str(release / "source"))
        self.assertEqual(data["runtime"], str(release / "runtime.json"))
        self.assertEqual(data["auto_update"], "false")
        self.assertEqual(data["args"], ["two words", "$(touch nope)"])

    def test_failure_before_activation_preserves_previous_release_and_skills(self):
        old = self.install()
        old_target = os.readlink(self.prefix / "current")
        with (
            self.local_dependencies(),
            patch.object(installer, "smoke_check", side_effect=RuntimeError("broken CLI")),
            self.assertRaisesRegex(RuntimeError, "broken CLI"),
        ):
            installer.install(self.source, self.prefix, self.skills)
        self.assertEqual(os.readlink(self.prefix / "current"), old_target)
        self.assertEqual(list((self.prefix / "releases").iterdir()), [old])
        self.assertEqual((self.skills / "lorehub").resolve(), old / "source/skills/lorehub")

    def test_failed_first_install_publishes_nothing(self):
        with (
            self.local_dependencies(),
            patch.object(installer, "smoke_check", side_effect=RuntimeError("bad")),
            self.assertRaises(RuntimeError),
        ):
            installer.install(self.source, self.prefix, self.skills)
        self.assertFalse(os.path.lexists(self.prefix / "current"))
        self.assertFalse(self.skills.exists())
        self.assertFalse((self.prefix / "bin").exists())

    def test_activation_failure_removes_only_links_created_by_transaction(self):
        with (
            self.local_dependencies(),
            patch.object(installer.os, "replace", side_effect=OSError("disk failed")),
            self.assertRaisesRegex(OSError, "disk failed"),
        ):
            installer.install(self.source, self.prefix, self.skills)
        for name in common.COMMANDS:
            self.assertFalse(os.path.lexists(self.prefix / "bin" / name))
        for name in common.SKILLS:
            self.assertFalse(os.path.lexists(self.skills / name))
        self.assertFalse(os.path.lexists(self.prefix / "current"))

    def test_upgrade_reuses_owned_links(self):
        old = self.install()
        new = self.install()
        self.assertNotEqual(old, new)
        self.assertTrue(old.is_dir())
        self.assertEqual((self.skills / "mubu-integration").resolve(), new / "source/modules/mubu-cli")
        for name in common.COMMANDS:
            self.assertEqual(os.readlink(self.prefix / "bin" / name), f"../current/bin/{name}")

    def test_existing_foreign_skill_directory_and_broken_symlink_are_not_overwritten(self):
        self.skills.mkdir()
        for name, make in [("cubox", lambda p: p.mkdir()),
                           ("mubu-integration", lambda p: p.symlink_to(self.base / "absent"))]:
            with self.subTest(name=name):
                foreign = self.skills / name
                make(foreign)
                with self.assertRaisesRegex(common.PackagingError, "non-LoreHub"):
                    self.install()
                self.assertTrue(os.path.lexists(foreign))
                self.assertFalse(os.path.lexists(self.prefix / "current"))
                foreign.unlink() if foreign.is_symlink() else foreign.rmdir()

    def test_conflict_does_not_switch_existing_current(self):
        old = self.install(skills=False)
        put(self.skills, "soota/SKILL.md", "user content")
        with self.assertRaises(common.PackagingError):
            self.install()
        self.assertEqual((self.prefix / "current").resolve(), old)
        self.assertEqual((self.skills / "soota/SKILL.md").read_text(), "user content")

    def test_global_cli_and_pythonpath_are_never_fallbacks(self):
        release = self.install()
        poison = self.base / "global tools"
        touched = self.base / "global-was-used"
        for name in common.COMMANDS:
            put(poison, name, f"#!/bin/sh\n/usr/bin/touch {shlex.quote(str(touched))}\nexit 0\n", True)
        modules = self.base / "global modules"
        put(modules, "lorehub/__init__.py", "raise RuntimeError('wrong Python module')\n")
        env = dict(os.environ, PATH=str(poison), PYTHONPATH=str(modules))
        for name in common.COMMANDS:
            result = subprocess.run([self.prefix / "bin" / name, "--help"], env=env, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
        (release / "venv/bin/soota").unlink()
        (release / "bin/cubox-cli").unlink()
        (release / "source/modules/mubu-cli/scripts/mubu_api.py").unlink()
        for name in ("soota", "cubox-cli", "mubu-cli"):
            with self.subTest(name=name):
                try:
                    result = subprocess.run([self.prefix / "bin" / name], env=env, capture_output=True, check=False)
                    self.assertNotEqual(result.returncode, 0)
                except FileNotFoundError:
                    pass
        self.assertFalse(touched.exists())

    def test_no_registration_without_explicit_skills_dir(self):
        release = self.install(skills=False)
        self.assertTrue((release / "skills/mubu-integration/SKILL.md").is_file())
        self.assertFalse(self.skills.exists())

    def test_conflicting_command_is_not_replaced(self):
        existing = put(self.prefix, "bin/soota", "existing user's CLI")
        with self.assertRaisesRegex(common.PackagingError, "non-LoreHub"):
            self.install()
        self.assertEqual(existing.read_text(), "existing user's CLI")

    def test_bundle_tamper_and_extra_files_fail_before_prefix_creation(self):
        for name in ("packaging/prebuilt/cubox-cli", "packaging/requirements.lock", "src/lorehub/cli.py",
                     "modules/mubu-cli/docs/guide.md", "packaging/wheels/unlisted.whl"):
            with self.subTest(name=name):
                target = self.source / name
                original = target.read_bytes() if target.exists() else None
                target.write_text("tampered")
                with self.assertRaisesRegex(common.PackagingError, "inventory/hash"):
                    self.install()
                self.assertFalse(self.prefix.exists())
                target.write_bytes(original) if original is not None else target.unlink()

    def test_component_mismatch_fails_even_when_bundle_hash_is_resealed(self):
        (self.source / "modules/cubox-cli/main.go").write_text("wrong component revision")
        common.seal_bundle(self.source)
        with self.assertRaises(subprocess.CalledProcessError):
            self.install()
        self.assertFalse(self.prefix.exists())

    def test_component_verifier_missing_is_not_silently_skipped(self):
        (self.source / "src/lorehub/components.py").unlink()
        common.seal_bundle(self.source)
        with self.assertRaisesRegex(common.PackagingError, "verify\\(root\\)"):
            self.install()

    def test_bundle_mode_and_platform_tamper_fail(self):
        binary = self.source / "packaging/prebuilt/cubox-cli"
        binary.chmod(0o644)
        with self.assertRaises(common.PackagingError):
            self.install()
        binary.chmod(0o755)
        value = json.loads((self.source / common.BUNDLE).read_text())
        value["platform"] = "unsupported"
        common.write_json(self.source / common.BUNDLE, value)
        with self.assertRaisesRegex(common.PackagingError, "platform"):
            self.install()

    def test_release_without_go_does_not_call_source_builder(self):
        with patch.object(installer, "build_payload", side_effect=AssertionError("must not run Go")):
            self.install()

    def test_explicit_source_selection_excludes_private_cache_and_git(self):
        for name in [".git/config", ".private/data.json", "dist/previous.tar.gz", "cache/session",
                     "modules/soota/docs/private/plan.md", "modules/mubu-cli/.env.credentials",
                     "modules/cubox-cli/cache/snapshot.json", "packaging/__pycache__/common.pyc"]:
            self.assertFalse(common.allowed(name), name)
        for name in ["modules/mubu-cli/docs/AGENT_CONTRACT.md", "modules/mubu-cli/scripts/mubu/cli.py",
                     "modules/cubox-cli/go.sum", "packaging/requirements.lock"]:
            self.assertTrue(common.allowed(name), name)

    def test_uv_uses_private_python_and_drops_dependency_overrides(self):
        with patch.dict(os.environ, {"UV_NO_VERIFY_HASHES": "true", "UV_PYTHON": "/wrong/python",
                                     "PIP_EXTRA_INDEX_URL": "https://invalid", "VIRTUAL_ENV": "/wrong"}):
            env = common.uv_environment(self.base / "toolchain")
        self.assertEqual(env["UV_PYTHON_INSTALL_DIR"], str(self.base / "toolchain/python"))
        self.assertEqual(env["UV_PYTHON_INSTALL_BIN"], "false")
        self.assertNotIn("UV_NO_VERIFY_HASHES", env)
        self.assertNotIn("PIP_EXTRA_INDEX_URL", env)
        self.assertNotIn("VIRTUAL_ENV", env)


if __name__ == "__main__":
    unittest.main()
