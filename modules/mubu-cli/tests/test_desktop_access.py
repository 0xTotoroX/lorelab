"""桌面文件权限错误不能伪装成未登录，也不能触发云端写入。"""

import errno
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from mubu import cli
from mubu.config import DesktopDataAccessError, MubuError
from mubu.desktop import data_root, read_session


@pytest.mark.parametrize("stage", ["storage", "collection", "file"])
def test_session_access_denial_is_explicit(tmp_path, monkeypatch, stage):
    storage = tmp_path / ".storage"
    collection = storage / "mubu_desktop_app-rxdb-1-users"
    collection.mkdir(parents=True)
    token_file = collection / "001.log"
    token_file.write_text(json.dumps({"id": 1, "|u": "fixture-token"}))
    target = {"storage": storage, "collection": collection, "file": token_file}[stage]
    method = "read_bytes" if stage == "file" else "iterdir"
    original = getattr(Path, method)

    def guarded(path, *args, **kwargs):
        if path == target:
            raise PermissionError(errno.EPERM, "Operation not permitted", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, method, guarded)
    with pytest.raises(DesktopDataAccessError) as error:
        read_session(tmp_path)
    assert "fixture-token" not in str(error.value)


def test_discovery_does_not_skip_denied_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("MUBU_DATA_ROOT", raising=False)
    denied = (tmp_path / "Library/Containers/com.mubu.mas/Data/Library/Application Support"
              / "Mubu/mubu_app_data/mubu_data/.storage")
    fallback = tmp_path / "Library/Application Support/Mubu/mubu_app_data/mubu_data/.storage"
    fallback.mkdir(parents=True)
    original = Path.stat

    def guarded(path, *args, **kwargs):
        if path == denied:
            raise PermissionError(errno.EACCES, "Permission denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded)
    with pytest.raises(DesktopDataAccessError):
        data_root()
    with pytest.raises(DesktopDataAccessError):
        data_root(str(denied.parent))


def test_readable_empty_storage_remains_missing_login(tmp_path):
    (tmp_path / ".storage").mkdir()
    with pytest.raises(MubuError, match="未找到可用的桌面登录记录"):
        read_session(tmp_path)


@pytest.mark.parametrize("command", [["auth-status"], ["create", "fixture"]])
def test_agent_reports_access_denial_before_requests(tmp_path, monkeypatch, capsys, command):
    storage = tmp_path / ".storage"
    storage.mkdir()
    original = Path.iterdir

    def guarded(path):
        if path == storage:
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", guarded)
    request = Mock(side_effect=AssertionError("network request"))
    monkeypatch.setattr("requests.Session.request", request)
    monkeypatch.setattr("sys.argv", ["mubu", "--agent", "--auth", "desktop",
                                    "--data-root", str(tmp_path), *command])
    with pytest.raises(SystemExit) as error:
        cli.main()
    result = json.loads(capsys.readouterr().out)
    assert error.value.code == 1
    assert result["status"] == "error"
    assert result["error"]["code"] == "DESKTOP_ACCESS_DENIED"
    assert result["error"]["next_action"] == "grant_desktop_data_access"
    assert result["error"]["retryable"] is False
    request.assert_not_called()
