import json

import pytest

from soota.errors import AuthBudgetError, ContractError, InputError, SourceError
from soota.providers import opencli_commands
from soota.providers.opencli import OpenCLIProvider
from soota.providers.opencli_errors import failure
from soota.providers.opencli_runtime import OpenCLIRuntime, RuntimeUnavailable
from soota.providers.process import ProcessResult
from tests.unit.test_opencli import REAL_RUN


@pytest.fixture
def runtime(monkeypatch):
    row = {
        "command": "youtube/video",
        "site": "youtube",
        "name": "video",
        "access": "read",
        "browser": False,
        "args": [],
    }
    monkeypatch.setattr(OpenCLIRuntime, "resolve", lambda self: ("fixture", "managed"))
    monkeypatch.setattr(opencli_commands, "commands", lambda settings: [row])
    monkeypatch.setattr("soota.providers.opencli.preflight", lambda *args: None)
    monkeypatch.setattr(OpenCLIProvider, "_run", REAL_RUN)
    calls = []

    def install(result):
        def process(argv, **kwargs):
            if "--version" in argv:
                return ProcessResult(0, "1.8.8", "")
            calls.append(argv)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(opencli_commands, "run_process", process)
        monkeypatch.setattr("soota.providers.opencli.run_process", process)

    return row, calls, install


@pytest.mark.parametrize("channel", ["stderr-json", "stdout-json", "stderr-yaml"])
@pytest.mark.parametrize(
    "code,message,exit_code,kind,category,reason,retryable",
    [
        ("ARGUMENT", "Bad value", 2, InputError, "input", "invalid_arguments", False),
        ("AUTH_REQUIRED", "Not logged in", 77, AuthBudgetError, "auth", "login_required", False),
        ("FORBIDDEN", "Forbidden", 77, AuthBudgetError, "permission", "access_denied", False),
        ("COMMAND_EXEC", "HTTP 429 rate limit", 1, AuthBudgetError, "rate_limit", "access_throttled", False),
        ("COMMAND_EXEC", "filter layout (ambiguous_option)", 1, ContractError, "contract", "ambiguous_option", False),
        ("COMMAND_EXEC", "Navigation rejected", 1, SourceError, "transient", "navigation_rejected", True),
        ("TIMEOUT", "Page timed out", 75, SourceError, "transient", "timeout", True),
        ("COMMAND_EXEC", "fetch failed", 1, SourceError, "transient", "network_error", True),
        ("UNKNOWN", "Something happened", 1, SourceError, "unknown", "upstream_failure", False),
    ],
)
def test_native_and_standard_share_safe_typed_diagnostics(
    settings, runtime, channel, code, message, exit_code, kind, category, reason, retryable
):
    row, calls, install = runtime
    sensitive = (
        "https://private.example.test/private-doc?xsec_token=synthetic-token Authorization: Bearer synthetic-secret"
    )
    envelope = {
        "ok": False,
        "error": {
            "code": code,
            "message": message + " " + sensitive,
            "help": sensitive,
            "headers": {"Cookie": "private-cookie"},
            "exitCode": exit_code,
        },
        "trace": {"dir": "/private/account/path"},
    }
    output = (
        json.dumps(envelope)
        if channel.endswith("json")
        else f"error:\n  code: {code}\n  message: {message}\n  help: {sensitive}"
    )
    install(
        ProcessResult(exit_code, output if channel == "stdout-json" else "", output if channel != "stdout-json" else "")
    )
    errors = []
    for run in (
        lambda: opencli_commands.execute(settings, row, {}, allow_write=False),
        lambda: OpenCLIProvider(settings)._run("youtube", "video", []),
    ):
        with pytest.raises(kind) as caught:
            run()
        error = caught.value.to_dict()
        errors.append(error)
        assert error["hint"]
        assert error["details"] == {
            "exit_code": exit_code,
            "upstream_code": code,
            "attempts": 1,
            "category": category,
            "reason": reason,
            "retryable": retryable,
        }
        rendered = json.dumps(error)
        assert all(
            secret not in rendered
            for secret in (
                "private.example",
                "synthetic-token",
                "synthetic-secret",
                "private-cookie",
                "/private/account",
            )
        )
    assert errors[0] == errors[1]
    assert len(calls) == 2  # One dispatch per entrypoint; even transient failures are not replayed.


@pytest.mark.parametrize("access", ["read", "write"])
@pytest.mark.parametrize("reason", ["timeout", "output_limit"])
def test_process_limits_do_not_replay(settings, runtime, access, reason):
    row, calls, install = runtime
    row["access"] = access
    install(SourceError("unsafe raw diagnostic", details={"reason": reason}))
    with pytest.raises(SourceError) as caught:
        opencli_commands.execute(settings, row, {}, allow_write=True)
    assert caught.value.details["retryable"] is (access == "read" and reason == "timeout")
    assert caught.value.details["exit_code"] is None
    assert "unsafe" not in str(caught.value)
    assert len(calls) == 1


def test_write_transient_is_not_retryable_and_is_not_replayed(settings, runtime):
    row, calls, install = runtime
    row["access"] = "write"
    install(ProcessResult(75, "", "code: TIMEOUT\nmessage: timed out"))
    with pytest.raises(SourceError) as caught:
        opencli_commands.execute(settings, row, {}, allow_write=True)
    assert caught.value.details["retryable"] is False and len(calls) == 1


@pytest.mark.parametrize("body", ["not json with synthetic-secret", "<html>private account</html>"])
def test_bad_json_is_a_nonretryable_contract_failure(settings, runtime, body):
    row, calls, install = runtime
    install(ProcessResult(0, body, ""))
    with pytest.raises(ContractError) as caught:
        opencli_commands.execute(settings, row, {}, allow_write=False)
    assert caught.value.details["reason"] == "invalid_json"
    assert caught.value.details["retryable"] is False and len(calls) == 1
    assert body not in str(caught.value)


def test_unknown_upstream_code_is_not_echoed():
    error = failure(
        ProcessResult(1, "", "code: PRIVATE_ACCOUNT_SECRET\nmessage: unknown"), operation="fixture/read", read_only=True
    )
    assert error.details["upstream_code"] == "UNKNOWN"
    assert "PRIVATE_ACCOUNT" not in json.dumps(error.to_dict())


def test_upstream_hint_does_not_reclassify_login_as_rate_limit():
    payload = {"error": {"code": "LOGIN_WALL", "message": "HTML login wall", "help": "Log in or wait out a rate limit"}}
    error = failure(ProcessResult(77, "", json.dumps(payload)), operation="fixture/read", read_only=True)
    assert error.details["category"] == "auth"


def test_unsupported_browser_surface_reports_reconnect_without_raw_message(settings, runtime):
    row, calls, install = runtime
    row.update(command="xiaohongshu/search", site="xiaohongshu", name="search")
    message = "Xiaohongshu search failed: Creating browser windows from extensions is not supported in Owl."
    install(ProcessResult(1, "", json.dumps({"error": {"code": "COMMAND_EXEC", "message": message}})))
    with pytest.raises(RuntimeUnavailable) as caught:
        opencli_commands.execute(settings, row, {}, allow_write=False)
    assert caught.value.details == {
        "exit_code": 1,
        "upstream_code": "COMMAND_EXEC",
        "attempts": 1,
        "category": "unavailable",
        "reason": "browser_surface_unsupported",
        "retryable": False,
    }
    assert "Google Chrome Browser Bridge" in caught.value.hint and "OPENCLI_PROFILE" in caught.value.hint
    assert message not in json.dumps(caught.value.to_dict())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "value",
    [
        "abc123",
        "https://www.xiaohongshu.com/explore/abc123",
        "https://www.xiaohongshu.com/explore/abc123?xsec_token=",
        "https://www.xiaohongshu.com/explore/abc123?xsec_token=%20",
        "https://xhslink.com/example",
        "https://[broken",
    ],
)
def test_unsigned_note_fails_before_runtime_or_dispatch(settings, monkeypatch, value):
    monkeypatch.setattr(OpenCLIRuntime, "resolve", lambda self: pytest.fail("must not resolve or dispatch"))
    with pytest.raises(InputError) as caught:
        opencli_commands.execute(settings, {"command": "xiaohongshu/note"}, {"note-id": value}, allow_write=False)
    assert caught.value.details == {
        "category": "input",
        "reason": "missing_signed_note_url",
        "retryable": False,
        "dispatched": False,
        "attempts": 0,
    }
    assert "搜索" in caught.value.hint and value not in str(caught.value)


@pytest.mark.parametrize("path", ["explore/abc123", "search_result/abc123", "user/profile/abc/abc123"])
def test_signed_note_is_dispatched_unchanged(settings, runtime, path):
    row, calls, install = runtime
    row.update(
        command="xiaohongshu/note",
        site="xiaohongshu",
        name="note",
        args=[{"name": "note-id", "type": "str", "positional": True, "required": True}],
    )
    url = f"https://www.xiaohongshu.com/{path}?xsec_token=synthetic-signature&xsec_source=pc_search"
    install(ProcessResult(0, "[]", ""))
    assert opencli_commands.execute(settings, row, {"note-id": url}, allow_write=False) == []
    assert calls[0][-1] == url
