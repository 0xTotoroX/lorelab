"""知识进程边界：失败证据私有、有界且不重试；不调用真实服务。"""

import json
import subprocess
import traceback
from unittest.mock import Mock

import pytest

from lorelab.knowledge import runtime


@pytest.fixture
def process(monkeypatch):
    monkeypatch.setattr(runtime, "tool_command", lambda tool: ["/synthetic-component"])
    monkeypatch.setattr(runtime, "tool_environment", dict)
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    return run


def diagnostic_path(receipt):
    return receipt.with_name(receipt.name + ".diagnostic.json")


def public_trace(error):
    return "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("code", [0, 1, 27])
@pytest.mark.parametrize("stdout", ["", "not JSON", "<html>upstream error</html>"])
def test_non_json_always_fails_once_without_overwriting_receipt(tmp_path, process, code, stdout):
    receipt = tmp_path / "private" / "execute.json"
    runtime.private_json(receipt, {"preserved": True})
    original = receipt.read_bytes()
    process.return_value = subprocess.CompletedProcess([], code, stdout, "upstream failed")

    with pytest.raises(runtime.ToolError, match="未返回有效 JSON") as error:
        runtime.run_json("cubox", ["synthetic-operation"], receipt, (0, 1, 27))

    process.assert_called_once()
    assert process.call_args.kwargs["timeout"] == 600
    assert process.call_args.kwargs["check"] is False
    assert receipt.read_bytes() == original
    path = diagnostic_path(receipt)
    assert str(path) in str(error.value)
    assert "不可直接重发" in str(error.value)
    assert json.loads(path.read_bytes()) == {
        "schema_version": 1,
        "failure": "invalid_json",
        "returncode": code,
        "stdout": {"type": "text", "size_bytes": len(stdout.encode("utf-8"))},
        "stderr": {"type": "text", "size_bytes": len(b"upstream failed")},
    }
    assert path.stat().st_mode & 0o777 == 0o600


def test_large_secret_output_is_metadata_only(tmp_path, process):
    receipt = tmp_path / "private" / "execute.json"
    secrets = ["opaque-secret-value", "Bearer abc123", "Cookie: session=xyz", "password=abc"]
    args = ["--token", secrets[0]]
    stdout = "not json\n" + "\n".join(secrets) + "中" * 1_000_000
    stderr = "Authorization: " + "\n".join(secrets) + "x" * 2_000_000
    process.return_value = subprocess.CompletedProcess([], 9, stdout, stderr)

    with pytest.raises(runtime.ToolError) as error:
        runtime.run_json("cubox", args, receipt)

    process.assert_called_once()
    path = diagnostic_path(receipt)
    content = path.read_text()
    assert path.stat().st_size < 1024
    assert json.loads(content)["stdout"]["size_bytes"] == len(stdout.encode("utf-8"))
    assert json.loads(content)["stderr"]["size_bytes"] == len(stderr)
    for secret in [*secrets, "Authorization", "--token", "/synthetic-component"]:
        assert secret not in content
        assert secret not in public_trace(error)
    assert not receipt.exists()


@pytest.mark.parametrize("partial", [None, b"\xff\x00opaque-secret", "中opaque-secret"])
def test_timeout_keeps_partial_metadata_and_suppresses_command_chain(tmp_path, process, partial):
    receipt = tmp_path / "execute.json"
    runtime.private_json(receipt, {"prior": "valid receipt"})
    original = receipt.read_bytes()
    args = ["--password", "argv-secret"]
    process.side_effect = subprocess.TimeoutExpired(
        ["/synthetic-component", *args], 600, output=partial, stderr=b"stderr-secret"
    )

    with pytest.raises(runtime.ToolError, match="超时") as error:
        runtime.run_json("cubox", args, receipt)

    process.assert_called_once()
    assert receipt.read_bytes() == original
    path = diagnostic_path(receipt)
    value = json.loads(path.read_bytes())
    assert value["failure"] == "timeout"
    assert value["returncode"] is None
    expected_type = "none" if partial is None else "bytes" if isinstance(partial, bytes) else "text"
    size = 0 if partial is None else len(partial.encode("utf-8") if isinstance(partial, str) else partial)
    assert value["stdout"] == {"type": expected_type, "size_bytes": size}
    assert value["stderr"] == {"type": "bytes", "size_bytes": len(b"stderr-secret")}
    assert str(path) in str(error.value)
    assert "不可直接重发" in str(error.value)
    for secret in ("opaque-secret", "argv-secret", "stderr-secret", "--password", "/synthetic-component"):
        assert secret not in path.read_text()
        assert secret not in public_trace(error)


@pytest.mark.parametrize("timeout", [False, True])
def test_failure_without_receipt_never_saves_diagnostic(tmp_path, monkeypatch, process, timeout):
    save = Mock(side_effect=AssertionError("must not write without receipt"))
    monkeypatch.setattr(runtime, "private_json", save)
    if timeout:
        process.side_effect = subprocess.TimeoutExpired(["argv-secret"], 600, stderr=b"stderr-secret")
    else:
        process.return_value = subprocess.CompletedProcess([], 1, "stdout-secret", "stderr-secret")
    with pytest.raises(runtime.ToolError, match="未指定私有回执路径") as error:
        runtime.run_json("cubox", [])
    process.assert_called_once()
    save.assert_not_called()
    assert "secret" not in public_trace(error)


@pytest.mark.parametrize("timeout", [False, True])
def test_diagnostic_write_failure_preserves_original_failure(tmp_path, monkeypatch, process, timeout):
    receipt = tmp_path / "execute.json"
    runtime.private_json(receipt, {"prior": True})
    original = receipt.read_bytes()
    save = Mock(side_effect=OSError("filesystem-secret"))
    monkeypatch.setattr(runtime, "private_json", save)
    if timeout:
        process.side_effect = subprocess.TimeoutExpired(["argv-secret"], 600)
    else:
        process.return_value = subprocess.CompletedProcess([], 1, "bad", "stderr-secret")
    with pytest.raises(runtime.ToolError, match="超时" if timeout else "未返回有效 JSON") as error:
        runtime.run_json("cubox", [], receipt)
    process.assert_called_once()
    save.assert_called_once()
    assert "未能保存" in str(error.value)
    assert str(diagnostic_path(receipt)) in str(error.value)
    assert "secret" not in public_trace(error)
    assert receipt.read_bytes() == original


def test_diagnostic_symlink_is_not_followed(tmp_path, process):
    receipt = tmp_path / "execute.json"
    target = tmp_path / "protected.json"
    target.write_text("preserved")
    diagnostic_path(receipt).symlink_to(target)
    process.return_value = subprocess.CompletedProcess([], 1, "bad", "stderr-secret")
    with pytest.raises(runtime.ToolError, match="未能保存"):
        runtime.run_json("cubox", [], receipt)
    process.assert_called_once()
    assert target.read_text() == "preserved"
    assert not receipt.exists()


@pytest.mark.parametrize("code,acceptable,ok", [(0, (0,), True), (1, (0, 1), True), (1, (0,), False)])
@pytest.mark.parametrize("value", [{"status": "partial", "items": []}, [1, "中"], None])
def test_valid_json_receipt_contract_is_unchanged(tmp_path, process, code, acceptable, ok, value):
    receipt = tmp_path / "private" / "execute.json"
    process.return_value = subprocess.CompletedProcess([], code, json.dumps(value), "ignored stderr")
    if ok:
        assert runtime.run_json("cubox", [], receipt, acceptable) == value
    else:
        with pytest.raises(runtime.ToolError, match="执行失败"):
            runtime.run_json("cubox", [], receipt, acceptable)
    process.assert_called_once()
    assert json.loads(receipt.read_bytes()) == value
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert not diagnostic_path(receipt).exists()


@pytest.mark.parametrize("stderr,fields", [
    ("HTTP 100:", {"http_status": 100}),
    ("Error: HTTP 599:", {"http_status": 599}),
    ('{"error":"HTTP 403:', {"http_status": 403}),
    ('{\n  "error": "HTTP 503:', {"http_status": 503}),
    ("API error 0:", {"api_error_code": 0}),
    ("Error: API error -9999999999:", {"api_error_code": -9999999999}),
    ('{"error":"API error +9999999999:', {"api_error_code": 9999999999}),
])
@pytest.mark.parametrize("timeout", [False, True])
def test_stderr_whitelist_saves_only_bounded_codes(tmp_path, process, stderr, fields, timeout):
    receipt = tmp_path / "execute.json"
    secret = "Authorization: Bearer opaque-credential https://private.invalid/path?token=opaque-credential"
    # 正文中的另一种错误不能被继续识别；大正文也不能扩大私有诊断。
    stderr += secret + " HTTP 418: API error -7:" + "中" * 100_000
    if timeout:
        process.side_effect = subprocess.TimeoutExpired(["argv-secret"], 600, stderr=stderr.encode("utf-8"))
    else:
        process.return_value = subprocess.CompletedProcess([], 1, "not JSON", stderr)
    with pytest.raises(runtime.ToolError) as error:
        runtime.run_json("cubox", [], receipt)
    process.assert_called_once()
    path = diagnostic_path(receipt)
    diagnostic = json.loads(path.read_bytes())
    assert diagnostic["stderr"] == {
        "type": "bytes" if timeout else "text", "size_bytes": len(stderr.encode("utf-8")), **fields,
    }
    assert path.stat().st_size < 1024
    for private in ("Authorization", "opaque-credential", "https://private.invalid", "argv-secret"):
        assert private not in path.read_text()
        assert private not in public_trace(error)


@pytest.mark.parametrize("stderr", [
    "HTTP 099:", "HTTP 600:", "HTTP 1000:", "HTTP +200:", "HTTP ２００:",
    "API error 12345678901:", "API error --1:", "API error １２:", "API error 1Authorization:",
    "API error " + "9" * 100_000 + ":",
    "Error: HTTP 200Authorization:", "Error: API error -1Authorization:",
    "Authorization: Bearer HTTP 403:", "Authorization: secret\nError: HTTP 403:",
    '{"error":"Authorization: HTTP 403:', '{"other":"HTTP 403:',
    "Error: request to https://private.invalid failed: HTTP 503:",
    "Error: HTTP 500", "Error: API error -5", "Error: \nHTTP 503:",
    "x" * 4096 + "Error: HTTP 503:", "中" * 4096 + "API error -7:",
])
def test_stderr_unmatched_or_embedded_codes_remain_metadata_only(tmp_path, process, stderr):
    receipt = tmp_path / "execute.json"
    stderr += " Authorization: Bearer opaque-credential"
    process.return_value = subprocess.CompletedProcess([], 1, "not JSON", stderr)
    with pytest.raises(runtime.ToolError) as error:
        runtime.run_json("cubox", [], receipt)
    process.assert_called_once()
    path = diagnostic_path(receipt)
    assert json.loads(path.read_bytes())["stderr"] == {
        "type": "text", "size_bytes": len(stderr.encode("utf-8")),
    }
    assert path.stat().st_size < 1024
    for private in ("Authorization", "opaque-credential", "https://private.invalid"):
        assert private not in path.read_text()
        assert private not in public_trace(error)
