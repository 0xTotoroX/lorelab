"""首次配置、升级、重复执行及失败保全的行为测试。"""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest
from test_install import common, fixture_environment, fixture_source, installer, put

from lorelab import cli, maintenance, setup, updates


@pytest.fixture
def installed(tmp_path, monkeypatch):
    source = tmp_path / "bundle"
    fixture_source(source)
    prefix = tmp_path / "product"
    monkeypatch.setattr(installer, "get_uv", lambda *_: Path("/unused/uv"))
    monkeypatch.setattr(installer, "install_environment", fixture_environment)
    release = installer.install(source, prefix)
    monkeypatch.setattr(maintenance, "managed_installation", lambda: (prefix, (prefix / "current").resolve()))
    monkeypatch.setattr(maintenance, "installer", lambda: installer)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LORELAB_CONFIG_FILE", str(tmp_path / "settings.json"))
    return source, prefix, release


def setup_args(*args):
    return cli.parser().parse_args(["setup", "--non-interactive", "--shell-profile", "none", *map(str, args)])


def update_args(*args):
    return cli.parser().parse_args(["update", *map(str, args)])


def test_setup_preserves_config_unknown_fields_and_existing_cleanup_gate(installed, tmp_path):
    config = tmp_path / "settings.json"
    original = {"vault": str(tmp_path), "subdir": "notes", "delete_verified": True,
                "custom": {"keep": 42}, "mubu_doc": "old"}
    config.write_text(json.dumps(original))
    result = setup.setup(setup_args("--mubu-doc", "new"))
    assert result["config_changed"]
    assert json.loads(config.read_text()) == {**original, "mubu_doc": "new"}
    assert "cleanup_after" not in json.loads(config.read_text())


def test_new_mubu_document_does_not_inherit_old_parent_and_accepts_explicit_parent(installed, tmp_path):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"vault": str(tmp_path), "subdir": "notes",
                                  "mubu_doc": "old-doc", "mubu_parent": "old-node"}))
    setup.setup(setup_args("--mubu-doc", "new-doc"))
    assert "mubu_parent" not in json.loads(config.read_text())
    setup.setup(setup_args("--mubu-doc", "third-doc", "--mubu-parent", "new-node"))
    assert json.loads(config.read_text())["mubu_parent"] == "new-node"
    setup.setup(setup_args("--mubu-parent", ""))
    assert json.loads(config.read_text())["mubu_parent"] == ""


def test_bash_login_can_find_installed_cli_and_profile_preserves_crlf(installed, tmp_path, monkeypatch):
    _source, prefix, _release = installed
    monkeypatch.setenv("SHELL", "/bin/bash")
    Path.home().mkdir()
    profile = Path.home() / ".bash_profile"
    original = b"# user configuration\r\n"
    profile.write_bytes(original)
    setup.setup(setup_args("--shell-profile", "auto"))
    assert profile.read_bytes().startswith(original)
    output = subprocess.check_output(["/bin/bash", "--login", "-c", "command -v lorelab"], text=True)
    assert output.strip() == str(prefix / "bin/lorelab")


def test_setup_repeat_keeps_config_profile_tasks_and_registration(installed, tmp_path):
    _source, prefix, _release = installed
    vault = tmp_path / "vault"
    vault.mkdir()
    profile = tmp_path / "profile"
    profile.write_text("# user settings\n")
    task = tmp_path / "jobs/existing.json"
    task.parent.mkdir()
    task.write_text('{"state":"verified"}')
    args = setup_args("--vault", vault, "--subdir", "知识", "--shell-profile", profile)
    first = setup.setup(args)
    config = Path(first["config"])
    tracked = [config, profile, task, prefix / "install.json"]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tracked}
    second = setup.setup(setup_args("--shell-profile", profile))
    assert not second["config_changed"]
    assert not second["files_updated"]
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tracked}
    assert json.loads(config.read_text())["delete_verified"] is False
    for name in common.SKILLS:
        assert (Path.home() / ".agents/skills" / name / "SKILL.md").is_file()


def test_setup_conflict_leaves_config_and_profile_unchanged(installed, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    profile = tmp_path / "profile"
    profile.write_text("user profile")
    put(Path.home(), ".agents/skills/soota/SKILL.md", "user skill")
    with pytest.raises(RuntimeError, match="overwrite"):
        setup.setup(setup_args("--vault", vault, "--shell-profile", profile))
    assert not (tmp_path / "settings.json").exists()
    assert profile.read_text() == "user profile"


def test_setup_rollback_restores_config_when_activation_fails(installed, tmp_path):
    profile = tmp_path / "profile"
    profile.write_text("before\n")
    with patch.object(installer, "activate", side_effect=OSError("switch failed")), pytest.raises(OSError):
        setup.setup(setup_args("--vault", tmp_path, "--shell-profile", profile))
    assert profile.read_text() == "before\n"
    assert not (tmp_path / "settings.json").exists()


def test_setup_does_not_read_accounts_without_explicit_check(installed):
    with patch.object(setup, "account_checks", side_effect=AssertionError("no cloud query")):
        result = setup.setup(setup_args("--no-skills", "--no-bin"))
    assert result["accounts"] == []


def test_setup_skills_only_plugin_mode_does_not_register_duplicate_skills(installed):
    setup.setup(setup_args("--no-skills"))
    assert not (Path.home() / ".agents/skills").exists()


def test_update_check_noop_and_new_release_preserve_config_and_tasks(installed, tmp_path):
    source, prefix, release = installed
    setup.setup(setup_args("--vault", tmp_path))
    config = tmp_path / "settings.json"
    before = config.read_bytes()
    result = updates.update(update_args("--from", source, "--check"))
    assert not result["available"]
    same = updates.update(update_args("--from", source))
    assert not same["changed"]
    put(source, "docs/overview.md", "next release")
    common.seal_bundle(source)
    assert updates.update(update_args("--from", source, "--check"))["available"]
    assert (prefix / "current").resolve() == release
    upgraded = updates.update(update_args("--from", source))
    assert upgraded["changed"]
    assert release.exists()
    assert config.read_bytes() == before
    assert len(list((prefix / "releases").iterdir())) == 2
    assert (Path.home() / ".agents/skills/soota/SKILL.md").is_file()


def test_update_bad_archive_or_hash_keeps_previous_install(installed, tmp_path):
    _source, prefix, release = installed
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(b"not a tar")
    for args in (("--from", archive), ("--from", archive, "--sha256", "0" * 64)):
        with pytest.raises(ValueError):
            updates.update(update_args(*args))
    assert (prefix / "current").resolve() == release


def test_update_needs_explicit_source_without_configured_feed(installed):
    with pytest.raises(ValueError, match="尚未配置更新源"):
        updates.update(update_args())


def test_local_feed_selects_relative_archive_and_rejects_wrong_platform(installed, tmp_path):
    feed = tmp_path / "latest.json"
    feed.write_text(json.dumps({"schema_version": 1, "product": "lorelab",
                               "platform": common.platform_tag(), "url": "bundle"}))
    setup.setup(setup_args("--update-feed", feed, "--no-skills", "--no-bin"))
    assert not updates.update(update_args())["changed"]
    value = json.loads(feed.read_text())
    value["platform"] = "linux-arm64"
    feed.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="平台"):
        updates.update(update_args())


def test_remote_download_reuses_verified_bytes_and_repairs_bad_cache(tmp_path):
    content = b"synthetic release"
    expected = hashlib.sha256(content).hexdigest()
    with patch.object(updates, "remote_open", return_value=io.BytesIO(content)) as request:
        target, cached = updates.download("https://example.org/release", expected, tmp_path)
        assert not cached
        assert target.read_bytes() == content
        assert request.call_count == 1
    with patch.object(updates, "remote_open", side_effect=AssertionError("no duplicate download")):
        assert updates.download("https://example.org/release", expected, tmp_path) == (target, True)
    target.write_bytes(b"corrupt")
    with patch.object(updates, "remote_open", return_value=io.BytesIO(content)):
        assert updates.download("https://example.org/release", expected, tmp_path) == (target, False)


def test_bad_remote_hash_never_publishes_cache(tmp_path):
    with patch.object(updates, "remote_open", return_value=io.BytesIO(b"bad")), pytest.raises(ValueError, match="SHA256"):
        updates.download("https://example.org/release", "0" * 64, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", ["http://example.org/file", "file:///etc/passwd", "https://user:pass@example.org/file"])
def test_untrusted_transport_rejected(url):
    with pytest.raises(ValueError):
        updates.validate_location(url)


@pytest.mark.parametrize("name,kind", [("../outside", "file"), ("link", "symlink"), ("device", "device")])
def test_archive_cannot_escape_or_create_special_files(tmp_path, name, kind):
    path = tmp_path / "evil.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        entry = tarfile.TarInfo(name)
        if kind == "symlink":
            entry.type, entry.linkname = tarfile.SYMTYPE, "/tmp/outside"
        elif kind == "device":
            entry.type = tarfile.CHRTYPE
        archive.addfile(entry)
    with pytest.raises(ValueError), updates.unpack(path):
        pytest.fail("unsafe archive accepted")


def test_shared_python_is_under_prefix_and_cache_is_not_deleted(tmp_path):
    release = tmp_path / "prefix/releases/candidate"
    fixture_source(release / "source")
    cache = tmp_path / "prefix/toolchain/cache/keep"
    cache.parent.mkdir(parents=True)
    cache.write_text("cached download")
    with patch.object(installer, "create_venv", return_value=release / "venv/bin/python") as create, \
         patch.object(installer, "run"):
        installer.install_environment(release, Path("/unused/uv"))
    env = create.call_args.args[2]
    assert env["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / "prefix/toolchain/python")
    assert cache.read_text() == "cached download"
