import json
from pathlib import Path

import pytest

from soota.config import PaymentConfig
from soota.errors import InputError, SourceError
from soota.feature_aliases import ALIASES, alias_params
from soota.features import call_feature, list_features, show_feature
from soota.providers import opencli_commands
from soota.providers.opencli_commands import argument_value, command_arguments
from soota.providers.opencli_runtime import RuntimeUnavailable
from soota.providers.process import ProcessResult
from soota.providers.tikhub.registry import load_registry

ROWS = json.loads((Path(__file__).parents[1] / "fixtures/opencli_commands.json").read_text())


@pytest.fixture(autouse=True)
def discovery(monkeypatch):
    monkeypatch.setattr(opencli_commands, "commands", lambda settings: ROWS)


def test_union_and_all_native_plans(settings):
    result = list_features(settings, limit=5000)
    features = result.data["features"]
    assert len(features) == len(ROWS) + len(load_registry().preferred()) + len(ALIASES)
    assert all(row["plans"] for row in features)
    assert next(row for row in features if row["id"] == "twitter.profile")["plans"][0]["provider"] == "opencli"
    unsupported = next(row for row in features if row["id"] == "tikhub.tiktok.web.device_register")
    assert unsupported["callable"] and unsupported["requires_allow_write"]
    filtered = list_features(settings, site="twitter", provider="opencli", limit=1)
    assert filtered.data["next_offset"] == 1
    assert filtered.data["features"][0]["site"] == "twitter"


@pytest.mark.parametrize("alias", ALIASES, ids=lambda a: a.id)
def test_all_overlap_mappings_validate_both_provider_contracts(settings, alias):
    values = {"username": "example", "uid": "123456789012345678", "answer_id": "12345", "query": "hello"}
    value = values.get(alias.parameter)
    if alias.id.startswith("bilibili."):
        value = "https://www.bilibili.com/video/BV1M1421t7hT"
    elif alias.id.startswith("youtube."):
        value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    elif alias.id.startswith("xiaohongshu."):
        value = "https://www.xiaohongshu.com/explore/123456?xsec_token=private-test-token"
    params = [f"{alias.parameter}={value}"]
    cheap = call_feature(settings, alias.id, params=params, provider="opencli", dry_run=True)
    paid = call_feature(settings, alias.id, params=params, provider="tikhub", dry_run=True)
    assert cheap.ok and paid.ok
    assert cheap.data["plan"]["provider"] == "opencli"
    assert paid.data["provider"] == "tikhub"
    assert "private-test-token" not in json.dumps(cheap.model_dump()) + json.dumps(paid.model_dump())


def test_priority_explicit_override_and_unavailable_fallback(settings, monkeypatch):
    monkeypatch.setattr(opencli_commands, "execute", lambda *args, **kwargs: {"from": "browser"})
    assert call_feature(settings, "twitter.profile", params=["username=example"]).data["provider"] == "opencli"
    settings.payment = PaymentConfig(mode="auto", default_provider="tikhub")
    result = call_feature(settings, "twitter.profile", params=["username=example"], dry_run=True)
    assert result.data["provider"] == "tikhub"
    assert (
        call_feature(settings, "twitter.profile", params=["username=example"], provider="auto").data["provider"]
        == "opencli"
    )

    def unavailable(settings):
        raise RuntimeUnavailable("missing")

    monkeypatch.setattr(opencli_commands, "commands", unavailable)
    result = call_feature(settings, "twitter.profile", params=["username=example"], provider="auto", dry_run=True)
    assert result.data["provider"] == "tikhub"
    with pytest.raises(RuntimeUnavailable):
        call_feature(settings, "twitter.profile", params=["username=example"], provider="opencli")
    assert list_features(settings).warnings


def test_failure_after_dispatch_never_falls_back(settings, monkeypatch):
    def fail(*args, **kwargs):
        raise SourceError("429")

    monkeypatch.setattr(opencli_commands, "execute", fail)
    with pytest.raises(SourceError):
        call_feature(settings, "twitter.profile", params=["username=example"])


def test_false_and_option_injection_preserve_values():
    row = {
        "args": [
            {"name": "query", "type": "str", "positional": True, "required": True},
            {"name": "enabled", "type": "bool", "default": True},
        ]
    }
    assert command_arguments(row, {"query": "--help; $(touch nope)", "enabled": "false"}) == [
        "--enabled=false",
        "--",
        "--help; $(touch nope)",
    ]
    with pytest.raises(InputError):
        command_arguments(row, {"query": "x", "unknown": 1})
    row["args"].insert(0, {"name": "optional", "type": "str", "positional": True})
    with pytest.raises(InputError):
        command_arguments(row, {"query": "x"})


@pytest.mark.parametrize(
    "kind,value", [("boolean", "yes"), ("boolean", 1), ("int", "1.5"), ("number", "nan"), ("str", 123)]
)
def test_argument_types_reject_ambiguous_values(kind, value):
    with pytest.raises(InputError):
        argument_value({"name": "input", "type": kind}, value)


def test_native_write_requires_opt_in_and_does_not_start_process(settings, monkeypatch):
    row = {
        "site": "fixture",
        "name": "post",
        "command": "fixture/post",
        "args": [],
        "browser": False,
        "access": "write",
    }
    monkeypatch.setattr(
        "soota.providers.opencli_commands.run_process", lambda *args, **kwargs: pytest.fail("no dispatch")
    )
    monkeypatch.setattr(opencli_commands, "commands", lambda settings: [row])
    monkeypatch.setattr("soota.providers.opencli_commands.OpenCLIRuntime.resolve", lambda self: ("fixture", "external"))
    with pytest.raises(InputError, match="allow-write"):
        opencli_commands.execute(settings, row, {}, allow_write=False)


def test_nonbrowser_public_command_needs_no_browser_and_accepts_object_json(settings, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "soota.providers.opencli_commands.OpenCLIRuntime.resolve", lambda self: ("opencli-fixture", "external")
    )
    monkeypatch.setattr("soota.providers.opencli_commands.preflight", lambda *args: pytest.fail("no browser"))
    monkeypatch.setattr(
        "soota.providers.opencli_commands.run_process",
        lambda argv, **kwargs: seen.append(argv) or ProcessResult(0, '{"ok": true}', ""),
    )
    row = {"site": "fixture", "name": "read", "command": "fixture/read", "args": [], "browser": False, "access": "read"}
    monkeypatch.setattr(opencli_commands, "commands", lambda settings: [row])
    assert opencli_commands.execute(settings, row, {}, allow_write=False) == {"ok": True}
    assert seen == [["opencli-fixture", "fixture", "read", "-f", "json"]]


def test_auxiliary_tikhub_contract_exposed_but_requires_opt_in(settings):
    with pytest.raises(SourceError):
        call_feature(settings, "tikhub.tiktok.web.device_register", dry_run=True)
    result = call_feature(settings, "tikhub.tiktok.web.device_register", allow_write=True, dry_run=True)
    assert result.ok
    assert (
        show_feature(settings, "tikhub.tiktok.web.device_register").data["feature"]["path"].endswith("device_register")
    )


def test_search_mapping_does_not_claim_identical_pagination(settings):
    alias = next(a for a in ALIASES if a.id == "twitter.post.search")
    cheap, paid = alias_params(alias, {"query": "from:example", "sort": "latest"})
    assert cheap["product"] == "live" and paid["search_type"] == "Latest"
    with pytest.raises(InputError):
        alias_params(alias, {"query": "x", "limit": "50"})


def test_named_defaults_are_not_marked_as_user_input():
    row = {
        "args": [
            {"name": "prompt", "type": "str", "positional": True, "required": True},
            {"name": "model", "type": "str", "default": "sonnet"},
            {"name": "enabled", "type": "boolean", "default": True},
        ]
    }
    assert command_arguments(row, {"prompt": "hello"}) == ["--", "hello"]
    assert command_arguments(row, {"prompt": "hello", "enabled": False}) == ["--enabled=false", "--", "hello"]


def test_new_runtime_write_contract_cannot_use_old_read_authorization(settings, monkeypatch):
    old = {"site": "test", "name": "action", "command": "test/action", "access": "read", "browser": False, "args": []}
    current = {**old, "access": "write"}
    monkeypatch.setattr(opencli_commands, "commands", lambda settings: [current])
    monkeypatch.setattr("soota.providers.opencli_commands.OpenCLIRuntime.resolve", lambda self: ("fixture", "managed"))
    monkeypatch.setattr(opencli_commands, "run_process", lambda *a, **kw: pytest.fail("must block changed contract"))
    with pytest.raises(InputError, match="allow-write"):
        opencli_commands.execute(settings, old, {}, allow_write=False)


@pytest.mark.parametrize("path", ["search_result/123", "note/123", "user/profile/456/123"])
def test_xiaohongshu_signed_paths(path):
    alias = next(a for a in ALIASES if a.id == "xiaohongshu.note.detail")
    url = f"https://www.xiaohongshu.com/{path}?xsec_token=secret"
    cheap, paid = alias_params(alias, {"url": url})
    assert cheap == {"note-id": url}
    assert paid == {"note_id": "123", "xsec_token": "secret"}


def test_native_passcode_is_redacted_in_preview(settings, monkeypatch):
    row = {
        "site": "quark",
        "name": "save",
        "command": "quark/save",
        "access": "write",
        "browser": True,
        "args": [{"name": "passcode", "type": "str"}],
    }
    monkeypatch.setattr(opencli_commands, "commands", lambda settings: [row])
    result = call_feature(settings, "opencli.quark.save", params=["passcode=1234"], dry_run=True)
    assert "1234" not in json.dumps(result.model_dump())


def test_integer_parameters_do_not_round_long_ids():
    ident = "123456789012345678901"
    assert argument_value({"name": "id", "type": "int"}, ident) == ident


def test_auxiliary_price_endpoint_does_not_reserve_its_own_free_preflight(settings):
    path = "/api/v1/tikhub/user/get_endpoint_info"
    calls = []

    def request(method, endpoint, params):
        calls.append((endpoint, params["endpoint"]))
        return {"data": {"endpoint_uri": params["endpoint"], "endpoint_cost": 0}}

    result = call_feature(
        settings,
        "tikhub.tikhub.user.get_endpoint_info",
        params=["endpoint=/api/v1/tikhub/user/get_user_info"],
        allow_write=True,
        requester=request,
    )
    assert result.ok
    assert calls == [(path, path), (path, "/api/v1/tikhub/user/get_user_info")]
    assert result.data["reserved_cost_usd"] == 0
