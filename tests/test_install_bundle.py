"""发行选择、哈希与归档边界，构建步骤使用小型本地 payload。"""

import fcntl
import importlib.util
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_install import PACKAGING, common, fixture_source, installer, put

spec = importlib.util.spec_from_file_location("lorehub_builder", PACKAGING / "build_release.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lorehub bundle ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "source"
        fixture_source(self.root)

    def test_archive_keeps_component_sources_excludes_private_and_is_stable(self):
        for name in [".private/secrets.json", "dist/old.tar.gz", "cache/session.json",
                     "modules/mubu-cli/.local/token", "modules/soota/docs/private/plan.md"]:
            put(self.root, name, "MUST NOT SHIP")
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(["git", "-C", self.root, "add", "."], check=True)
        put(self.root, "modules/mubu-cli/untracked-secret.json", "MUST NOT SHIP")

        def payload(root, scratch, uv):
            put(root, "packaging/prebuilt/cubox-cli", "#!/bin/sh\nexit 0\n", True)
            put(root, "packaging/wheels/example.whl", "fixed wheel bytes")

        with patch.object(builder, "build_payload", side_effect=payload), \
             patch.object(builder, "get_uv", return_value=Path("/unused/uv")):
            first = builder.build(self.root, self.base / "first")
            second = builder.build(self.root, self.base / "second")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        checksum = first.with_name(first.name + ".sha256").read_text().split()[0]
        self.assertEqual(common.sha256(first), checksum)
        extracted = self.base / "extracted"
        with tarfile.open(first) as archive:
            for entry in archive.getmembers():
                self.assertFalse(entry.issym() or entry.islnk())
                self.assertEqual((entry.uid, entry.gid, entry.mtime), (0, 0, 0))
                self.assertNotIn(".git/", entry.name)
                self.assertNotIn("untracked-secret", entry.name)
                self.assertNotIn("MUST NOT SHIP", archive.extractfile(entry).read().decode(errors="replace"))
            archive.extractall(extracted, filter="data")
        unpacked = next(extracted.iterdir())
        common.verify_bundle(unpacked)
        common.verify_components(unpacked)
        for path in ("modules/cubox-cli/main.go", "modules/mubu-cli/scripts/mubu_api.py",
                     "modules/mubu-cli/docs/guide.md", "skills/lorehub/SKILL.md", "NOTICE.md", "uv.lock"):
            self.assertTrue((unpacked / path).is_file(), path)

    def test_missing_bundle_manifest_never_falls_back_to_source_build(self):
        (self.root / common.BUNDLE).unlink()
        with (
            patch.object(installer, "build_payload", side_effect=AssertionError("must not build")),
            self.assertRaisesRegex(common.PackagingError, "no bundle manifest"),
        ):
            installer.install(self.root, self.base / "prefix")

    def test_tracked_worktree_changes_are_copied_but_untracked_files_are_not(self):
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(["git", "-C", self.root, "add", "."], check=True)
        lock = self.root / "components.lock.json"
        lock.write_text('{"refreshed_but_not_committed": true}\n')
        put(self.root, "modules/mubu-cli/untracked-secret.json", "private")
        files = common.source_files(self.root)
        destination = self.base / "snapshot"
        common.copy_source(self.root, destination, files)
        self.assertEqual((destination / "components.lock.json").read_bytes(), lock.read_bytes())
        self.assertFalse((destination / "modules/mubu-cli/untracked-secret.json").exists())

    def test_bundle_rejects_external_symlink_even_with_same_bytes(self):
        path = self.root / "packaging/requirements.lock"
        path.unlink()
        outside = put(self.base, "outside-lock", "")
        path.symlink_to(outside)
        with self.assertRaisesRegex(common.PackagingError, "symlink"):
            common.verify_bundle(self.root)

    def test_release_id_and_lock_hash_are_validated(self):
        path = self.root / common.BUNDLE
        original = json.loads(path.read_text())
        for field in ("release_id", "components_lock_sha256"):
            with self.subTest(field=field):
                common.write_json(path, {**original, field: "wrong"})
                with self.assertRaises(common.PackagingError):
                    common.verify_bundle(self.root)

    def test_overlapping_skill_and_command_directory_is_rejected(self):
        prefix = self.base / "prefix"
        with self.assertRaisesRegex(common.PackagingError, "overlap"):
            installer.install(self.root, prefix, prefix / "bin")

    def test_foreign_current_and_release_symlinks_are_not_modified(self):
        prefix = self.base / "prefix"
        prefix.mkdir()
        foreign = self.base / "foreign"
        foreign.mkdir()
        for name in ("current", "releases", "bin"):
            with self.subTest(name=name):
                link = prefix / name
                link.symlink_to(foreign)
                with self.assertRaises(common.PackagingError):
                    installer.install(self.root, prefix)
                self.assertEqual(os.readlink(link), str(foreign))
                link.unlink()

    def test_concurrent_install_fails_before_creating_a_release(self):
        prefix = self.base / "prefix"
        prefix.mkdir()
        with (prefix / ".install.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(common.PackagingError, "another installation"):
                installer.install(self.root, prefix)
        self.assertFalse((prefix / "releases").exists())


if __name__ == "__main__":
    unittest.main()
