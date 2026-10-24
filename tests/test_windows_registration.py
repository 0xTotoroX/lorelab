"""Windows 注册事务、PATH 通知和编码链路；非 Windows 使用临时文件和 API 模拟。"""

import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import install as installer
import platform_support
import windows_entries

from lorelab import windows_path


@pytest.fixture
def commands(tmp_path):
    launcher = tmp_path / "launcher.exe"
    launcher.write_bytes(b"synthetic native launcher")
    entry = tmp_path / "soota.exe"
    return entry, Path(str(entry) + ".json"), tmp_path / "prefix/bin/soota.exe", launcher


@pytest.mark.parametrize("name", ["entry", "sidecar"])
@pytest.mark.parametrize("kind", ["file", "directory", "dangling", "symlink"])
def test_existing_foreign_paths_are_never_overwritten(commands, name, kind, monkeypatch):
    entry, sidecar, target, launcher = commands
    foreign = entry if name == "entry" else sidecar
    outside = foreign.with_name("outside")
    if kind == "directory":
        foreign.mkdir()
    elif kind in {"dangling", "symlink"}:
        if kind == "symlink":
            outside.write_bytes(b"foreign contents")
        foreign.symlink_to(outside)
    else:
        foreign.write_bytes(b"foreign contents")
    before = foreign.lstat()
    monkeypatch.setattr(installer, "windows", lambda: True)
    with pytest.raises(installer.PackagingError):
        installer.check_link(entry, target)
    with pytest.raises(FileExistsError):
        windows_entries.create(entry, target, launcher)
    assert os.path.samestat(before, foreign.lstat())
    assert not os.path.lexists(sidecar if name == "entry" else entry)
    if kind == "dangling":
        assert not outside.exists()
    elif kind == "symlink":
        assert outside.read_bytes() == b"foreign contents"
    elif kind == "file":
        assert foreign.read_bytes() == b"foreign contents"


@pytest.mark.parametrize("name", ["entry", "sidecar"])
@pytest.mark.parametrize("dangling", [False, True])
def test_exclusive_creation_rejects_racing_file_or_link(commands, name, dangling, monkeypatch):
    entry, sidecar, target, launcher = commands
    raced = entry if name == "entry" else sidecar
    outside = raced.with_name("missing-external-file")
    original = windows_entries._open_exclusive

    def race(path):
        if path == raced:
            path.symlink_to(outside) if dangling else path.write_bytes(b"competing installation")
        return original(path)

    monkeypatch.setattr(windows_entries, "_open_exclusive", race)
    with pytest.raises(FileExistsError):
        windows_entries.create(entry, target, launcher)
    assert not os.path.lexists(sidecar if name == "entry" else entry)
    if dangling:
        assert raced.is_symlink() and not outside.exists()
    else:
        assert raced.read_bytes() == b"competing installation"


@pytest.mark.parametrize("name", ["entry", "sidecar"])
def test_partial_write_failure_removes_only_created_files(commands, name, monkeypatch):
    entry, sidecar, target, launcher = commands
    failed = entry if name == "entry" else sidecar
    original = windows_entries._open_exclusive
    opened = []

    def open_file(path):
        stream = original(path)
        opened.append(stream)
        if path != failed:
            return stream

        def broken_write(data):
            stream.write(data[:3])
            raise OSError("synthetic write failure")

        return SimpleNamespace(write=broken_write, fileno=stream.fileno,
                               close=stream.close, closed=False)

    monkeypatch.setattr(windows_entries, "_open_exclusive", open_file)
    with pytest.raises(OSError, match="synthetic write failure"):
        windows_entries.create(entry, target, launcher)
    assert not os.path.lexists(entry) and not os.path.lexists(sidecar)
    assert all(stream.closed for stream in opened)


@pytest.mark.skipif(os.name == "nt", reason="Windows 持有的独占句柄本身禁止替换；此处验证 Mac 模拟保护")
@pytest.mark.parametrize("name", ["entry", "sidecar"])
def test_rollback_preserves_replaced_directory_entry(commands, name):
    entry, sidecar, target, launcher = commands
    replaced = entry if name == "entry" else sidecar
    with (pytest.raises(RuntimeError, match="activation failed"),
          windows_entries.create(entry, target, launcher) as registration):
        foreign = replaced.with_name("foreign")
        foreign.write_bytes(b"new owner")
        os.replace(foreign, replaced)
        raise RuntimeError("activation failed")
    assert replaced.read_bytes() == b"new owner"
    assert not os.path.lexists(sidecar if name == "entry" else entry)
    assert all(stream.closed for _, stream in registration.files)


def test_committed_registration_is_reusable_but_never_rolled_back_later(commands):
    entry, sidecar, target, launcher = commands
    with windows_entries.create(entry, target, launcher) as registration:
        assert all(not stream.closed for _, stream in registration.files)
    assert windows_entries.owned(entry, target)
    registration.rollback()
    assert windows_entries.owned(entry, target)
    assert entry.read_bytes() == launcher.read_bytes()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["environment"] == {}


@pytest.fixture
def native_files(monkeypatch):
    """用临时文件模拟 Win32 句柄，核对真实 ctypes 适配函数的调用契约。"""
    if os.name == "nt":
        pytest.skip("此替换文件模拟仅用于非 Windows；其他注册测试在 Windows 直接使用原生句柄")
    paths = {}

    def create(path, access, sharing, security, disposition, flags, template):
        assert access == 0xC0010000 and sharing == 0 and disposition == 1
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        paths[descriptor] = Path(path)
        return descriptor

    def delete(handle, kind, info, size):
        assert kind == 4 and size == 1
        assert ctypes.cast(info, ctypes.POINTER(ctypes.c_ubyte)).contents.value == 1
        path = paths[handle]
        if path.exists() and os.path.samestat(os.fstat(handle), path.lstat()):
            path.unlink()
        return 1

    kernel = SimpleNamespace(CreateFileW=Mock(side_effect=create),
                             SetFileInformationByHandle=Mock(side_effect=delete), CloseHandle=Mock())
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=kernel), raising=False)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(
        open_osfhandle=lambda handle, flags: handle, get_osfhandle=lambda descriptor: descriptor))
    monkeypatch.setattr(windows_entries, "os", SimpleNamespace(
        name="nt", path=os.path, O_RDWR=os.O_RDWR, O_BINARY=0, fdopen=os.fdopen, close=os.close))
    return kernel


def test_native_rollback_deletes_by_held_handle_not_replaced_path(commands, native_files):
    entry, sidecar, target, launcher = commands
    with (pytest.raises(RuntimeError, match="activation failed"),
          windows_entries.create(entry, target, launcher) as registration):
        # 实际 Windows 会拒绝这种替换；即使模拟器强制替换，也只处置旧句柄。
        foreign = entry.with_name("foreign")
        foreign.write_bytes(b"another owner")
        os.replace(foreign, entry)
        raise RuntimeError("activation failed")
    assert entry.read_bytes() == b"another owner" and not sidecar.exists()
    assert native_files.CreateFileW.call_count == 2
    assert native_files.SetFileInformationByHandle.call_count == 2
    assert all(stream.closed for _, stream in registration.files)


def test_native_commit_closes_handles_without_marking_files_for_deletion(commands, native_files):
    entry, sidecar, target, launcher = commands
    with windows_entries.create(entry, target, launcher) as registration:
        assert all(not stream.closed for _, stream in registration.files)
    assert all(stream.closed for _, stream in registration.files)
    native_files.SetFileInformationByHandle.assert_not_called()
    assert entry.read_bytes() == launcher.read_bytes() and sidecar.is_file()


@pytest.fixture
def activation(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "windows", lambda: True)
    monkeypatch.setattr(platform_support, "windows", lambda: True)
    monkeypatch.setattr(installer, "directory_link",
                        lambda path, target: path.symlink_to(target, target_is_directory=True))
    prefix, bins = tmp_path / "prefix", tmp_path / "commands"

    def release(name):
        root = prefix / "releases" / name
        (root / "source/packaging/prebuilt").mkdir(parents=True)
        (root / "source/packaging/prebuilt/launcher.exe").write_bytes(b"launcher")
        (root / "runtime.json").write_text(json.dumps({"product": "lorelab", "release_id": name}))
        return root

    before, after = release("before"), release("after")
    installer.activate(prefix, before, None)
    return prefix, bins, before, after


def test_activation_failure_restores_record_and_cleans_new_external_entries(activation, monkeypatch):
    prefix, bins, before, after = activation
    record = (prefix / "install.json").read_bytes()
    old_entries = {p.name: p.read_bytes() for p in (prefix / "bin").iterdir()}
    original = installer.switch_directory

    def fail(pending, current):
        if pending.name.startswith(".current-"):
            raise OSError("synthetic activation failure")
        original(pending, current)

    monkeypatch.setattr(installer, "switch_directory", fail)
    with pytest.raises(OSError, match="synthetic activation failure"):
        installer.activate(prefix, after, None, bins)
    assert (prefix / "current").resolve() == before
    assert (prefix / "install.json").read_bytes() == record
    assert {p.name: p.read_bytes() for p in (prefix / "bin").iterdir()} == old_entries
    assert not list(bins.iterdir())


def test_activation_rechecks_foreign_entry_created_after_preflight(activation, monkeypatch):
    prefix, bins, before, after = activation
    original = installer.directory_link

    def race(path, target):
        original(path, target)
        bins.mkdir()
        (bins / "lorelab.exe").write_bytes(b"foreign command")

    monkeypatch.setattr(installer, "directory_link", race)
    with pytest.raises(installer.PackagingError, match="non-LoreLab Windows entry"):
        installer.activate(prefix, after, None, bins)
    assert (prefix / "current").resolve() == before
    assert (bins / "lorelab.exe").read_bytes() == b"foreign command"
    assert list(bins.iterdir()) == [bins / "lorelab.exe"]


@pytest.fixture
def registry(monkeypatch):
    values, events = {}, []

    def query(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name]

    def save(key, name, reserved, kind, value):
        values[name] = value, kind
        events.append("save")

    def delete(key, name):
        del values[name]
        events.append("delete")

    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_CURRENT_USER=1, REG_EXPAND_SZ=2, CreateKey=lambda *args: contextlib.nullcontext("key"),
        QueryValueEx=query, SetValueEx=save, DeleteValue=delete))
    monkeypatch.setattr(windows_path, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(windows_path, "notify_environment", lambda: events.append("notify"))
    return values, events


def test_path_notification_happens_only_after_successful_activation(tmp_path, registry):
    values, events = registry
    values["Path"] = "original;", 1
    with windows_path.user_path(tmp_path) as changed:
        assert changed and events == ["save"]
        events.append("activate")
    assert events == ["save", "activate", "notify"]
    assert values["Path"] == ("original;" + str(tmp_path / "bin"), 1)
    with windows_path.user_path(tmp_path) as changed:
        assert not changed
    assert events == ["save", "activate", "notify"]


@pytest.mark.parametrize("existing", [False, True])
def test_failed_activation_restores_user_path_without_notification(tmp_path, registry, existing):
    values, events = registry
    if existing:
        values["Path"] = "keep-original", 1
    before = values.copy()
    with pytest.raises(RuntimeError, match="activation failed"), windows_path.user_path(tmp_path):
        raise RuntimeError("activation failed")
    assert values == before and "notify" not in events


def test_disabled_path_configuration_does_not_write_or_notify(tmp_path, registry):
    values, events = registry
    with windows_path.user_path(tmp_path, enabled=False) as changed:
        assert not changed
    assert not values and not events


def test_notification_timeout_keeps_successful_path_update(tmp_path, registry, monkeypatch, capsys):
    values, events = registry

    def timeout():
        raise OSError("synthetic notification timeout")

    monkeypatch.setattr(windows_path, "notify_environment", timeout)
    with windows_path.user_path(tmp_path) as changed:
        assert changed
    assert values["Path"][0] == str(tmp_path / "bin") and events == ["save"]
    assert "用户 PATH 已保存" in capsys.readouterr().err


@pytest.mark.parametrize("success", [0, 1])
def test_environment_broadcast_uses_correct_message_and_bounded_timeout(monkeypatch, success):
    send = Mock(return_value=success)
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=SimpleNamespace(SendMessageTimeoutW=send)), raising=False)
    if success:
        windows_path.notify_environment()
    else:
        with pytest.raises(OSError, match="通知超时或失败"):
            windows_path.notify_environment()
    assert send.call_args.args[:6] == (0xFFFF, 0x001A, 0, "Environment", 0x0002, 1000)
    assert send.restype is ctypes.c_ssize_t
    assert send.argtypes[2] is ctypes.c_size_t


@pytest.mark.parametrize("name,boundary", [("install.ps1", "$RepositoryRoot ="),
                                         ("packaging/uv.ps1", "$UvExecutable =")])
def test_powershell_prologue_round_trips_unicode_from_legacy_codepage(name, boundary):
    shell = shutil.which("powershell.exe" if os.name == "nt" else "pwsh")
    if shell is None:
        pytest.skip("本机没有 PowerShell；编码链路保留给 PowerShell 环境实跑")
    text = (Path(__file__).resolve().parents[1] / name).read_text(encoding="utf-8")
    prologue = text[text.index("$ErrorActionPreference"):text.index(boundary)]

    def quote(value):
        return "'" + value.replace("'", "''") + "'"

    expected = "用户 中文 & space's"
    command = f"""
[Console]::InputEncoding = [Text.Encoding]::GetEncoding(936)
[Console]::OutputEncoding = [Text.Encoding]::GetEncoding(936)
$OutputEncoding = [Text.Encoding]::ASCII
{prologue}
$Native = & {quote(sys.executable)} -X utf8 -c {quote('print(' + repr(expected) + ')')}
$Piped = {quote(expected)} | & {quote(sys.executable)} -X utf8 -c 'import sys; print(sys.stdin.read().strip())'
@{{input=[Console]::InputEncoding.CodePage; output=[Console]::OutputEncoding.CodePage;
  pipeline=$OutputEncoding.CodePage; native=$Native; piped=$Piped}} | ConvertTo-Json -Compress
"""
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, encoding="utf-8", check=True, timeout=30)
    assert json.loads(result.stdout) == {"input": 65001, "output": 65001, "pipeline": 65001,
                                      "native": expected, "piped": expected}
