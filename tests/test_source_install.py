"""源码安装/更新、Windows 平台边界和保留用户工作区的行为验证。"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))

import platform_support
import pytest
import repository
import windows_entries
from test_install import common, fixture_environment, fixture_source, installer, put

from lorelab import cli, maintenance, setup, updates


def source_fixture(root):
    fixture_source(root)
    (root / common.BUNDLE).unlink()
    shutil.rmtree(root / "packaging/prebuilt")
    shutil.rmtree(root / "packaging/wheels")


def local_build(root, scratch, uv, toolchain=None):
    scratch.mkdir(parents=True)
    put(root, "packaging/prebuilt/cubox-cli", "#!/bin/sh\nprintf 'cubox\\n'\n", True)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")


def test_source_install_repeat_and_new_revision_preserve_existing_data(tmp_path, monkeypatch):
    source, prefix = tmp_path / "source", tmp_path / "prefix"
    source_fixture(source)
    git(source, "init", "-q", "-b", "main")
    commit(source)
    monkeypatch.setattr(installer, "get_uv", lambda *_: Path("/unused/uv"))
    monkeypatch.setattr(installer, "build_payload", local_build)
    monkeypatch.setattr(installer, "install_environment", fixture_environment)
    first = installer.install(source, prefix)
    keep = put(tmp_path, "config/settings.json", '{"keep":"中文"}')
    old = keep.read_bytes(), keep.stat().st_mtime_ns
    monkeypatch.setattr(installer, "build_payload", lambda *_: pytest.fail("same source must not rebuild"))
    assert installer.install(source, prefix) == first
    source.joinpath("docs/overview.md").write_text("next source")
    monkeypatch.setattr(installer, "build_payload", local_build)
    second = installer.install(source, prefix)
    assert second != first and first.is_dir()
    assert (keep.read_bytes(), keep.stat().st_mtime_ns) == old
    assert installer.settings(prefix)["source"]["repository"] == str(source)


def test_git_update_check_uses_committed_snapshot_keeps_dirty_checkout(tmp_path, monkeypatch):
    source, prefix = tmp_path / "source", tmp_path / "prefix"
    source_fixture(source)
    git(source, "init", "-q", "-b", "main")
    commit(source)
    monkeypatch.setattr(installer, "get_uv", lambda *_: Path("/unused/uv"))
    monkeypatch.setattr(installer, "build_payload", local_build)
    monkeypatch.setattr(installer, "install_environment", fixture_environment)
    before = installer.install(source, prefix)
    monkeypatch.setattr(maintenance, "managed_installation", lambda: (prefix, before))
    monkeypatch.setattr(maintenance, "installer", lambda: installer)
    args = cli.parser().parse_args(["update", "--check"])
    assert not updates.update(args)["available"]
    source.joinpath("docs/overview.md").write_text("committed new source")
    commit(source)
    expected = repository.fingerprint(source)
    source.joinpath("docs/overview.md").write_text("uncommitted developer edit")
    status = git(source, "status", "--porcelain")
    result = updates.update(args)
    assert result["available"] and result["source_fingerprint"] == expected
    assert git(source, "status", "--porcelain") == status
    assert (prefix / "current").resolve() == before
    assert len(list((prefix / "toolchain/repositories").iterdir())) == 2  # one cache and its lock


def test_failed_git_fetch_preserves_current(tmp_path, monkeypatch):
    source, prefix = tmp_path / "source", tmp_path / "prefix"
    source_fixture(source)
    git(source, "init", "-q", "-b", "main")
    commit(source)
    monkeypatch.setattr(installer, "get_uv", lambda *_: Path("/unused/uv"))
    monkeypatch.setattr(installer, "build_payload", local_build)
    monkeypatch.setattr(installer, "install_environment", fixture_environment)
    before = installer.install(source, prefix)
    monkeypatch.setattr(maintenance, "managed_installation", lambda: (prefix, before))
    monkeypatch.setattr(maintenance, "installer", lambda: installer)
    with pytest.raises(subprocess.CalledProcessError):
        updates.update(cli.parser().parse_args(["update", "--ref", "missing-branch"]))
    assert (prefix / "current").resolve() == before


def test_windows_paths_machine_alias_and_junction_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support, "windows", lambda: True)
    monkeypatch.setattr(common.platform, "system", lambda: "Windows")
    monkeypatch.setattr(common.platform, "machine", lambda: "AMD64")
    assert common.platform_tag() == "windows-amd64"
    assert platform_support.venv_bin(tmp_path) == tmp_path / "Scripts/python.exe"
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(); new.mkdir()
    current, pending = tmp_path / "current", tmp_path / "pending"
    current.symlink_to(old, target_is_directory=True)
    pending.symlink_to(new, target_is_directory=True)
    replace = os.replace

    def reject(src, dst):
        if src == pending:
            raise PermissionError("busy junction")
        replace(src, dst)

    monkeypatch.setattr(platform_support.os, "replace", reject)
    with pytest.raises(PermissionError):
        platform_support.switch_directory(pending, current)
    assert current.resolve() == old


def test_windows_generated_entry_checks_ownership_and_original_bytes(tmp_path):
    launcher = put(tmp_path, "launcher.exe", "synthetic PE")
    entry, target = tmp_path / "soota.exe", tmp_path / "prefix/current/soota.exe"
    with windows_entries.create(entry, target, launcher):
        pass
    assert windows_entries.owned(entry, target)
    entry.write_bytes(b"another executable")
    assert not windows_entries.owned(entry, target)
    with pytest.raises(FileExistsError):
        windows_entries.create(entry, target, launcher)


def test_windows_activation_registers_four_commands_and_skills_without_file_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support, "windows", lambda: True)
    monkeypatch.setattr(installer, "windows", lambda: True)
    prefix, skills, bins = tmp_path / "prefix", tmp_path / "skills", tmp_path / "bin"

    def junction(path, target):
        absolute = path.parent / target
        assert absolute.exists(), "junction target must already exist"
        path.symlink_to(target, target_is_directory=True)

    monkeypatch.setattr(installer, "directory_link", junction)

    def release(name):
        folder = prefix / "releases" / name
        put(folder, "runtime.json", '{"product":"lorelab","release_id":"' + name + '"}')
        put(folder, "source/packaging/prebuilt/launcher.exe", "native launcher")
        for command in common.COMMANDS:
            put(folder, "bin/" + command + ".exe", "component")
        for skill in common.SKILLS:
            put(folder, "skills/" + skill + "/SKILL.md", name)
        return folder

    first = release("first")
    installer.activate(prefix, first, skills, bins)
    for name in common.COMMANDS:
        path = bins / (name + ".exe")
        assert path.is_file() and not path.is_symlink()
        assert windows_entries.owned(path, prefix / "bin" / (name + ".exe"))
    second = release("second")
    installer.activate(prefix, second, None)
    assert (prefix / "current").resolve() == second
    assert all((skills / name / "SKILL.md").read_text() == "second" for name in common.SKILLS)
    assert first.is_dir()


def test_setup_normalizes_windows_subdirectory_without_changing_existing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LORELAB_CONFIG_FILE", str(tmp_path / "config.json"))
    args = cli.parser().parse_args(["setup", "--non-interactive", "--vault", str(tmp_path),
                                   "--subdir", "知识\\工具"])
    _, value, changed = setup.knowledge_settings(args)
    assert changed and value["subdir"] == "知识/工具"


@pytest.mark.parametrize("value", ["-upload-pack=bad", "https://user:secret@example.org/repo", "http://example.org/repo"])
def test_repository_rejects_option_or_embedded_credentials(value):
    with pytest.raises(RuntimeError):
        repository.validate_repository(value)
