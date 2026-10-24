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

spec = importlib.util.spec_from_file_location("lorelab_installer", PACKAGING / "install.py")
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
    put(root, "src/lorelab/__init__.py", "")
    put(root, "src/lorelab/cli.py", """import json, os, sys
if __name__ == '__main__':
    print(json.dumps({'root': os.environ['LOREHUB_ROOT'],
        'runtime': os.environ['LOREHUB_RUNTIME_FILE'], 'args': sys.argv[1:],
        'auto_update': os.environ['SOOTA_AUTO_UPDATE'],
        'new_root': os.environ.get('LORELAB_ROOT'), 'new_runtime': os.environ.get('LORELAB_RUNTIME_FILE'),
        'knowledge_runtime': os.environ.get('SOOTA_KNOWLEDGE_RUNTIME_FILE'),
        'knowledge_lock': os.environ.get('SOOTA_KNOWLEDGE_COMPONENTS_LOCK')}))
""")
    put(root, "src/lorelab/components.py", """import hashlib, json
def verify(root):
    expected = json.loads((root / 'components.lock.json').read_text())['test_sha256']
    actual = hashlib.sha256((root / 'modules/cubox-cli/main.go').read_bytes()).hexdigest()
    return {'ok': expected == actual}
""")
    code = put(root, "modules/cubox-cli/main.go", "package main\n")
    common.write_json(root / "components.lock.json", {"schema_version": 1,
        "product": {"name": "lorelab", "version": "0.1.0"}, "test_sha256": common.sha256(code)})
    for path in common.SKILLS.values():
        put(root, f"{path}/SKILL.md", "[Guide](docs/guide.md) and [entry](scripts/entry.py)\n")
        put(root, f"{path}/docs/guide.md", "[More](../references/more.md)\n")
        put(root, f"{path}/references/more.md", "Complete guide\n")
        put(root, f"{path}/scripts/entry.py", "# helper\n")
    with (root / "skills/lorelab/SKILL.md").open("a") as stream:
        stream.write("[Product overview](../../docs/overview.md)\n")
    put(root, "modules/mubu-cli/scripts/mubu_api.py", "import json,sys; print(json.dumps(sys.argv))\n")
    put(root, "packaging/requirements.lock", "")
    put(root, "packaging/build-requirements.lock", "")
    put(root, "packaging/prebuilt/cubox-cli", "#!/bin/sh\nprintf 'bundled cubox\\n'\n", True)
    put(root, "packaging/wheels/lorelab-0.1.0-py3-none-any.whl", "fixture only")
    put(root, "packaging/wheels/soota-0.1.0-py3-none-any.whl", "fixture only")
    common.seal_bundle(root)


def fixture_environment(release, uv):
    venv.EnvBuilder(with_pip=False, symlinks=True).create(release / "venv")
    site = next((release / "venv/lib").glob("python*/site-packages"))
    (site / "fixture.pth").write_text(str(release / "source/src") + "\n")
    put(release, "venv/bin/soota", "#!/bin/sh\nprintf 'bundled soota\\n'\n", True)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lorelab tests '")
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

    def legacy_install(self, product="lorehub"):
        """固定的旧安装布局，不经新安装器创建或重新解释旧 bundle。"""
        release = self.prefix / "releases/legacy-0.1.0"
        release.mkdir(parents=True)
        self.prefix.joinpath("current").symlink_to("releases/legacy-0.1.0")
        self.prefix.joinpath("bin").mkdir()
        self.skills.mkdir()
        commands = ["lorehub", "cubox-cli", "soota", "mubu-cli"]
        skills = ["lorehub", "cubox", "soota", "mubu-integration"]
        if product == "lorelab":
            commands.append("lorelab")
            skills.append("lorelab")
        for name in commands:
            put(release, f"bin/{name}", "#!/bin/sh\nprintf 'old release\\n'\n", True)
            self.prefix.joinpath("bin", name).symlink_to(f"../current/bin/{name}")
        for name in skills:
            put(release, f"skills/{name}/SKILL.md", "Old Skill\n")
            self.skills.joinpath(name).symlink_to(self.prefix / "current/skills" / name)
        put(release, "source/src/lorehub/__init__.py", "# Previous release remains untouched\n")
        common.write_json(release / "runtime.json", {"schema_version": 1, "product": product,
                                                   "release_id": release.name, "tools": {}})
        return release

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
        self.assertEqual(runtime["product"], "lorelab")
        self.assertEqual(runtime["source_root"], str(release / "source"))
        self.assertEqual(runtime["components_lock"], str(release / "source/components.lock.json"))
        self.assertEqual(runtime["release_id"], release.name)
        self.assertEqual(runtime["components_lock_sha256"], common.sha256(release / "source/components.lock.json"))
        self.assertEqual(runtime["tools"]["mubu"][1], str(release / "source/modules/mubu-cli/scripts/mubu_api.py"))
        for name in common.SKILLS:
            self.assertTrue((self.skills / name / "docs/guide.md").is_file())
            self.assertTrue((self.skills / name / "scripts/entry.py").is_file())
        self.assert_skill_closure(release)
        self.assertTrue((release / "source/NOTICE.md").is_file())
        self.assertTrue((release / "source/uv.lock").is_file())
        output = subprocess.check_output([self.prefix / "bin/lorelab", "two words", "$(touch nope)"], text=True)
        data = json.loads(output)
        self.assertEqual(data["root"], str(release / "source"))
        self.assertEqual(data["runtime"], str(release / "runtime.json"))
        self.assertEqual(data["new_root"], data["root"])
        self.assertEqual(data["new_runtime"], data["runtime"])
        self.assertEqual(data["knowledge_runtime"], data["runtime"])
        self.assertEqual(data["knowledge_lock"], str(release / "source/components.lock.json"))
        self.assertEqual(data["auto_update"], "false")
        self.assertEqual(data["args"], ["two words", "$(touch nope)"])
        self.assertEqual({p.name for p in (release / "bin").iterdir()},
                         {"lorelab", "cubox-cli", "soota", "mubu-cli"})
        self.assertEqual({p.name for p in (release / "skills").iterdir()},
                         {"lorelab", "cubox", "soota", "mubu-integration"})
        for path in (self.prefix / "bin/lorehub", self.skills / "lorehub",
                     release / "source/src/lorehub", release / "source/skills/lorehub"):
            self.assertFalse(os.path.lexists(path), path)
        subprocess.run([release / "venv/bin/python", "-I", "-B", "-c",
                        "import importlib.util; assert importlib.util.find_spec('lorehub') is None"], check=True)

    def test_failure_before_activation_preserves_previous_release_and_skills(self):
        old = self.legacy_install()
        old_target = os.readlink(self.prefix / "current")
        with (
            self.local_dependencies(),
            patch.object(installer, "smoke_check", side_effect=RuntimeError("broken CLI")),
            self.assertRaisesRegex(RuntimeError, "broken CLI"),
        ):
            installer.install(self.source, self.prefix, self.skills)
        self.assertEqual(os.readlink(self.prefix / "current"), old_target)
        self.assertEqual(list((self.prefix / "releases").iterdir()), [old])
        self.assertEqual((self.skills / "lorehub").resolve(), old / "skills/lorehub")
        self.assertEqual((self.prefix / "bin/lorehub").resolve(), old / "bin/lorehub")

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
        put(self.source, "docs/overview.md", "Updated product documentation\n")
        common.seal_bundle(self.source)
        new = self.install()
        self.assertNotEqual(old, new)
        self.assertTrue(old.is_dir())
        self.assertEqual((self.skills / "mubu-integration").resolve(), new / "source/modules/mubu-cli")
        for name in common.COMMANDS:
            self.assertEqual(os.readlink(self.prefix / "bin" / name), f"../current/bin/{name}")

    def test_identical_bundle_reuses_release_without_uv_or_environment_install(self):
        old = self.install()
        record = (self.prefix / "install.json").read_bytes()
        (self.skills / "cubox").unlink()
        with patch.object(installer, "get_uv", side_effect=AssertionError("no download")), \
             patch.object(installer, "install_environment", side_effect=AssertionError("no reinstall")):
            same = installer.install(self.source, self.prefix)
        self.assertEqual(old, same)
        self.assertEqual(list((self.prefix / "releases").iterdir()), [old])
        self.assertEqual((self.prefix / "install.json").read_bytes(), record)
        self.assertTrue((self.skills / "cubox/SKILL.md").is_file())

    def test_update_restores_recorded_skill_and_cli_registration_without_arguments(self):
        bins = self.base / "global bin"
        with self.local_dependencies():
            old = installer.install(self.source, self.prefix, self.skills, bins)
        put(self.source, "docs/overview.md", "Updated release\n")
        common.seal_bundle(self.source)
        (bins / "soota").unlink()
        with self.local_dependencies():
            new = installer.install(self.source, self.prefix)
        self.assertNotEqual(old, new)
        for name in common.COMMANDS:
            self.assertEqual((bins / name).resolve(), (new / "bin" / name).resolve())
        self.assertEqual((self.skills / "soota").resolve(), new / "source/modules/soota/skills/soota")

    def test_identical_bundle_does_not_hide_installed_corruption(self):
        old = self.install()
        (old / "source/docs/overview.md").write_text("changed after installation")
        with self.assertRaisesRegex(common.PackagingError, "inventory/hash"):
            self.install()
        self.assertEqual((self.prefix / "current").resolve(), old)

    def assert_legacy_upgrade(self, product):
        old = self.legacy_install(product)
        old_files = {p.relative_to(old).as_posix(): p.read_bytes()
                     for p in old.rglob("*") if p.is_file() and not p.is_symlink()}
        new = self.install()
        self.assertEqual((self.prefix / "current").resolve(), new)
        self.assertEqual(json.loads((new / "runtime.json").read_text())["product"], "lorelab")
        self.assertEqual({p.relative_to(old).as_posix(): p.read_bytes()
                          for p in old.rglob("*") if p.is_file() and not p.is_symlink()}, old_files)
        output = subprocess.check_output([self.prefix / "bin/lorelab", "--version"], text=True)
        self.assertEqual(json.loads(output)["root"], str(new / "source"))
        self.assertFalse(os.path.lexists(self.prefix / "bin/lorehub"))
        self.assertFalse(os.path.lexists(self.skills / "lorehub"))
        for name in common.COMMANDS:
            output = subprocess.check_output([self.prefix / "bin" / name, "--version"], text=True)
            self.assertTrue(output)
        for name in common.SKILLS:
            self.assertTrue((self.skills / name / "SKILL.md").is_file(), name)

    def test_legacy_prefix_upgrade_retires_owned_links_and_preserves_release(self):
        self.assert_legacy_upgrade("lorehub")

    def test_lorelab_prefix_upgrade_retires_owned_links_and_preserves_release(self):
        self.assert_legacy_upgrade("lorelab")

    def test_failed_activation_restores_retired_links_and_previous_current(self):
        old = self.legacy_install()
        legacy = [self.prefix / "bin/lorehub", self.skills / "lorehub"]
        original_links = {link: os.readlink(link) for link in legacy}
        current = os.readlink(self.prefix / "current")
        replace = os.replace

        def reject_switch(source, destination):
            if destination != self.prefix / "current":
                return replace(source, destination)
            for link in legacy:
                self.assertFalse(os.path.lexists(link))
            raise OSError("activation failed")

        with patch.object(installer.os, "replace", side_effect=reject_switch), \
             self.assertRaisesRegex(OSError, "activation failed"):
            self.install()
        self.assertEqual(os.readlink(self.prefix / "current"), current)
        self.assertEqual({link: os.readlink(link) for link in legacy}, original_links)
        self.assertFalse(os.path.lexists(self.prefix / "bin/lorelab"))
        self.assertFalse(os.path.lexists(self.skills / "lorelab"))
        self.assertEqual(list((self.prefix / "releases").iterdir()), [old])
        self.assertFalse(list(self.prefix.glob(".current-*")))
        self.assertFalse((self.prefix / "install.json").exists())
        self.assertEqual(subprocess.check_output([legacy[0]], text=True), "old release\n")

    def test_failed_retirement_restores_prior_link_without_switching_current(self):
        old = self.legacy_install()
        original_unlink = Path.unlink

        def reject_skill_removal(path, *args, **kwargs):
            if path == self.skills / "lorehub":
                self.assertFalse(os.path.lexists(self.prefix / "bin/lorehub"))
                raise OSError("cannot retire Skill")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", reject_skill_removal), \
             self.assertRaisesRegex(OSError, "cannot retire Skill"):
            self.install()
        self.assertEqual((self.prefix / "current").resolve(), old)
        self.assertEqual((self.prefix / "bin/lorehub").resolve(), old / "bin/lorehub")
        self.assertEqual((self.skills / "lorehub").resolve(), old / "skills/lorehub")
        self.assertEqual(list((self.prefix / "releases").iterdir()), [old])
        self.assertFalse(os.path.lexists(self.prefix / "bin/lorelab"))
        self.assertFalse(os.path.lexists(self.skills / "lorelab"))

    def test_legacy_skill_is_only_retired_in_explicit_skills_directory(self):
        old = self.legacy_install()
        skill_target = os.readlink(self.skills / "lorehub")
        new = self.install(skills=False)
        self.assertNotEqual(old, new)
        self.assertEqual(os.readlink(self.skills / "lorehub"), skill_target)
        self.assertFalse(os.path.lexists(self.prefix / "bin/lorehub"))

    def test_retirement_preserves_foreign_legacy_files_directories_and_symlinks(self):
        self.prefix.joinpath("bin").mkdir(parents=True)
        self.skills.mkdir()
        outside = put(self.base, "external/entry", "external content")
        for kind in ("file", "directory", "external-link", "dangling-link", "other-prefix-link"):
            with self.subTest(kind=kind):
                paths = [self.prefix / "bin/lorehub", self.skills / "lorehub"]
                for path in paths:
                    if kind == "file":
                        path.write_text("user content")
                    elif kind == "directory":
                        put(path, "keep.txt", "user content")
                    else:
                        target = outside if kind == "external-link" else self.base / kind / "current/bin/lorehub"
                        if kind == "other-prefix-link":
                            put(target.parent, target.name, "other prefix's entry")
                        path.symlink_to(target)
                previous = {p: os.readlink(p) for p in paths if p.is_symlink()}
                self.install()
                for path in paths:
                    if path in previous:
                        self.assertEqual(os.readlink(path), previous[path])
                        path.unlink()
                    elif kind == "directory":
                        self.assertEqual((path / "keep.txt").read_text(), "user content")
                        (path / "keep.txt").unlink()
                        path.rmdir()
                    else:
                        self.assertEqual(path.read_text(), "user content")
                        path.unlink()
                self.assertEqual(outside.read_text(), "external content")

    def test_symlink_parent_traversal_does_not_establish_legacy_link_ownership(self):
        self.legacy_install()
        external = self.base / "external"
        (external / "child").mkdir(parents=True)
        (self.prefix / "redirect").symlink_to(external / "child")
        paths = [(self.prefix / "bin/lorehub", "bin/lorehub"), (self.skills / "lorehub", "skills/lorehub")]
        for link, name in paths:
            link.unlink()
            put(external / "current", name, "foreign target")
            link.symlink_to(self.prefix / "redirect/../current" / name)
        original = {link: os.readlink(link) for link, _ in paths}
        self.install()
        for link, _ in paths:
            self.assertEqual(os.readlink(link), original[link])
            self.assertEqual(link.read_text(), "foreign target")

    def test_owned_broken_links_are_retired_without_modifying_their_targets(self):
        self.prefix.joinpath("bin").mkdir(parents=True)
        self.skills.mkdir()
        self.prefix.joinpath("bin/lorehub").symlink_to("../current/bin/lorehub")
        self.skills.joinpath("lorehub").symlink_to(self.prefix / "current/skills/lorehub")
        self.install()
        self.assertFalse(os.path.lexists(self.prefix / "bin/lorehub"))
        self.assertFalse(os.path.lexists(self.skills / "lorehub"))

    def test_soota_launcher_receives_independent_runtime_binding(self):
        release = self.install()
        installer.write_launcher(release / "venv/bin/soota", [release / "venv/bin/python", "-c",
            "import json,os; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith(('LORE','SOOTA_KNOWLEDGE'))}))"], {})
        output = subprocess.check_output([self.prefix / "bin/soota"], text=True)
        env = json.loads(output)
        self.assertEqual(env["LORELAB_ROOT"], env["LOREHUB_ROOT"])
        self.assertEqual(env["LORELAB_RUNTIME_FILE"], env["LOREHUB_RUNTIME_FILE"])
        self.assertEqual(env["SOOTA_KNOWLEDGE_RUNTIME_FILE"], str(release / "runtime.json"))
        self.assertEqual(env["SOOTA_KNOWLEDGE_COMPONENTS_LOCK"], str(release / "source/components.lock.json"))

    def test_missing_local_product_or_soota_wheel_never_uses_registry(self):
        release = self.base / "incomplete release"
        common.copy_source(self.source, release / "source", list(common.verify_bundle(self.source)["files"]))
        for package in ("lorelab", "soota"):
            with self.subTest(package=package):
                wheel = release / f"source/packaging/wheels/{package}-0.1.0-py3-none-any.whl"
                content = wheel.read_bytes()
                wheel.unlink()
                with patch.object(installer, "create_venv", return_value=release / "venv/bin/python"), \
                     patch.object(installer, "run", side_effect=AssertionError("registry must not be used")), \
                     self.assertRaisesRegex(common.PackagingError, f"local {package} wheel"):
                    installer.install_environment(release, Path("/unused/uv"))
                wheel.write_bytes(content)

    def test_wheel_install_has_both_local_packages_and_no_index(self):
        release = self.base / "offline release"
        common.copy_source(self.source, release / "source", list(common.verify_bundle(self.source)["files"]))
        with patch.object(installer, "create_venv", return_value=release / "venv/bin/python"), \
             patch.object(installer, "run") as run:
            installer.install_environment(release, Path("/unused/uv"))
        command = [str(arg) for arg in run.call_args_list[0].args[0]]
        self.assertIn("--no-index", command)
        self.assertIn("--no-deps", command)
        self.assertIn(str(release / "source/packaging/wheels/lorelab-0.1.0-py3-none-any.whl"), command)
        self.assertIn(str(release / "source/packaging/wheels/soota-0.1.0-py3-none-any.whl"), command)

    def test_existing_foreign_skill_directory_and_broken_symlink_are_not_overwritten(self):
        self.skills.mkdir()
        for name, make in [("cubox", lambda p: p.mkdir()),
                           ("mubu-integration", lambda p: p.symlink_to(self.base / "absent"))]:
            with self.subTest(name=name):
                foreign = self.skills / name
                make(foreign)
                with self.assertRaisesRegex(common.PackagingError, "non-LoreLab/LoreHub"):
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
        put(modules, "lorelab/__init__.py", "raise RuntimeError('wrong Python module')\n")
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
        with self.assertRaisesRegex(common.PackagingError, "non-LoreLab/LoreHub"):
            self.install()
        self.assertEqual(existing.read_text(), "existing user's CLI")

    def test_bundle_tamper_and_extra_files_fail_before_prefix_creation(self):
        for name in ("packaging/prebuilt/cubox-cli", "packaging/requirements.lock", "src/lorelab/cli.py",
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
        (self.source / "src/lorelab/components.py").unlink()
        common.seal_bundle(self.source)
        with self.assertRaisesRegex(common.PackagingError, "verify\\(root\\)"):
            self.install()

    def test_new_product_requires_canonical_cli_and_skill_without_legacy_fallback(self):
        for name in ("src/lorelab/cli.py", "skills/lorelab/SKILL.md"):
            with self.subTest(name=name):
                path = self.source / name
                content = path.read_bytes()
                path.unlink()
                common.seal_bundle(self.source)
                with self.assertRaisesRegex(common.PackagingError, "incomplete product"):
                    self.install()
                path.write_bytes(content)
                common.seal_bundle(self.source)

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
