import json

import pytest
from typer.testing import CliRunner

from soota.cli import app
from soota.errors import ContractError
from soota.mcp_cli import run_site
from soota.providers.mcp_client import StdioMCPClient
from soota.providers.mcp_contract import validate_read_command


def metadata(access="read"):
    return {
        "results": [
            {
                "site": "reddit",
                "name": "search",
                "access": access,
                "domain": "reddit.com",
                "args": [
                    {"name": "query", "type": "string", "required": True},
                    {"name": "limit", "type": "int", "min": 1, "max": 100},
                    {"name": "exact", "type": "boolean"},
                    {"name": "tags", "type": "array", "items": {"type": "string"}, "max": 2},
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": "test", "other": True},
        {"query": "test", "limit": True},
        {"query": "test", "limit": 101},
        {"query": "test", "exact": "false"},
        {"query": "test", "tags": ["a", "b", "c"]},
        {"query": "test", "tags": [1]},
        {"query": "test", "limit": float("nan")},
    ],
)
def test_discovered_contract_rejects_invalid_arguments(args):
    with pytest.raises(ContractError):
        validate_read_command(metadata(), "reddit", "search", args, None)


def test_discovered_read_command_accepts_typed_args_and_rejects_write():
    args = {"query": "test", "limit": 20, "exact": False, "tags": ["a"]}
    validate_read_command(metadata(), "reddit", "search", args, None)
    with pytest.raises(ContractError, match="只读契约"):
        validate_read_command(metadata("write"), "reddit", "search", args, None)


def test_site_names_cannot_escape_adapter_directory(settings):
    with pytest.raises(ContractError, match="名称"):
        StdioMCPClient(settings.opencli_mcp).call_site_readonly("../elsewhere", "read", {})


def test_mcp_cli_discovery_does_not_run_site(monkeypatch, settings):
    settings.opencli_mcp.enabled = True
    monkeypatch.setattr("soota.config.load_settings", lambda: settings)

    def search(self, name, args):
        assert name == "sites_search" and args == {"query": "reddit search", "limit": 20}
        return metadata()

    monkeypatch.setattr(StdioMCPClient, "call", search)
    result = CliRunner().invoke(app, ["mcp", "search", "reddit search", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["response"]["results"][0]["site"] == "reddit"


def test_mcp_run_saves_native_result_without_exposing_credentials(settings, tmp_path, monkeypatch):
    settings.opencli_mcp.enabled = True
    params = tmp_path / "params.json"
    params.write_text('{"auth":{"api_key":"private-test-value"}}')
    monkeypatch.setattr(
        StdioMCPClient, "call_site_readonly", lambda *a, **k: {"ok": True, "value": "private-test-value"}
    )
    output = tmp_path / "result.json"
    result = run_site(settings, "example", "read", params, output, False)
    assert result.ok and result.data["output"] == str(output)
    assert "private-test-value" not in output.read_text()
