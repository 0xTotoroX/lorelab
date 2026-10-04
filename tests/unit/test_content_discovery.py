from __future__ import annotations

from types import SimpleNamespace

from soota.content import discovery
from soota.errors import ContractError


def test_inventory_only_discovers_and_never_calls_site(settings, monkeypatch):
    class Runtime:
        def __init__(self, settings):
            pass

        def lock(self):
            from contextlib import nullcontext

            return nullcontext()

        def status(self):
            return {"available": True, "version": "1.8.8", "ownership": "managed"}

    monkeypatch.setattr(discovery, "OpenCLIRuntime", Runtime)
    rows = [
        {"command": "web/read", "access": "read", "browser": True, "args": [], "columns": []},
        {"command": "future/search", "access": "read", "browser": False, "args": []},
        {"command": "future/write", "access": "write", "browser": True, "args": []},
        {
            "command": "future/unsupported",
            "access": "read",
            "browser": False,
            "args": [{"name": "value", "type": "opaque"}],
        },
    ]
    monkeypatch.setattr(discovery.opencli_commands, "commands", lambda settings: rows)
    monkeypatch.setattr(discovery.opencli_commands, "execute", lambda *a, **kw: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(discovery, "_package_version", lambda name: "2.1.2")
    monkeypatch.setattr(discovery.shutil, "which", lambda name: "/fixture/bin/" + name)
    monkeypatch.setattr(discovery.importlib.util, "find_spec", lambda name: None)
    endpoint = SimpleNamespace(
        key="site.web.fetch_detail",
        summary="detail",
        callable=True,
        deprecated=False,
        query_schema={},
        tasks=["detail"],
    )
    monkeypatch.setattr(
        discovery, "load_registry", lambda: SimpleNamespace(as_of="fixture", preferred=lambda: [endpoint])
    )
    result = discovery.discover_capabilities(settings)
    capabilities = {r["operation"]: r for r in result["capabilities"]}
    assert capabilities["web/read"]["state"] == "standard"
    assert capabilities["future/search"]["state"] == "native"
    assert capabilities["future/write"]["state"] == "blocked"
    assert capabilities["future/unsupported"]["state"] == "discovered"
    assert all(row["verification"] is None for row in result["capabilities"])
    assert all(row["state"] != "verified" for row in result["capabilities"])
    assert result["providers"][0]["runtime_version"] == "1.8.8"
    assert result["providers"][1]["state"] == "blocked"
    assert result["providers"][1]["enabled"] is False
    assert result["providers"][2]["credentials_checked"] is False


def test_unavailable_runtime_is_reported_without_masking_other_providers(settings, monkeypatch):
    class Runtime:
        def __init__(self, settings):
            pass

        def lock(self):
            raise ContractError("bad registry")

    monkeypatch.setattr(discovery, "OpenCLIRuntime", Runtime)
    monkeypatch.setattr(discovery, "_package_version", lambda name: None)
    monkeypatch.setattr(discovery.shutil, "which", lambda name: None)
    monkeypatch.setattr(discovery.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(discovery, "load_registry", lambda: SimpleNamespace(as_of="fixture", preferred=lambda: []))
    result = discovery.discover_capabilities(settings)
    assert result["providers"][0]["state"] == "blocked"
    assert result["providers"][1]["state"] == "blocked"
    assert result["providers"][2]["state"] == "blocked"
    assert "ContractError" in result["warnings"][0]


def test_managed_tikhub_version_uses_selected_python(settings, monkeypatch):
    settings.tikhub.runtime_python = "/fixture/managed/python"
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return SimpleNamespace(returncode=0, stdout="2.2.0\n")

    monkeypatch.setattr(discovery, "run_process", run)
    assert discovery._tikhub_version(settings) == "2.2.0"
    assert seen[0][0] == "/fixture/managed/python"
    assert "-I" in seen[0]
