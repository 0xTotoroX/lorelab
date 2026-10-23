import json

import httpx
from typer.testing import CliRunner

from soota.cli import app
from soota.updates import check_updates


def _transport(request: httpx.Request) -> httpx.Response:
    assert request.method == "GET"
    url = str(request.url)
    if request.url.host == "registry.npmjs.org":
        assert request.headers.get("accept") != "application/vnd.github+json"
    if url.endswith("/opencli-mcp/latest"):
        return httpx.Response(200, json={"version": "0.0.23"})
    if url.endswith("/@jackwener%2fopencli/latest"):
        return httpx.Response(200, json={"version": "1.8.8"})
    if url.endswith("/pypi/tikhub/json"):
        return httpx.Response(200, json={"info": {"version": "2.1.2"}})
    if "/compare/" in url:
        relation = "diverged" if "/TikHub/" in url else "ahead"
        return httpx.Response(
            200,
            json={
                "status": relation,
                "ahead_by": 6 if relation == "diverged" else 1,
                "behind_by": 2 if relation == "diverged" else 0,
            },
        )
    if url.startswith("https://api.github.com/repos/"):
        return httpx.Response(200, json={"default_branch": "main", "pushed_at": "2026-09-27T00:00:00Z"})
    raise AssertionError(url)


def test_updates_check_separates_package_versions_from_repository_history(settings, monkeypatch):
    monkeypatch.setattr(
        "soota.updates._installed_versions",
        lambda settings: {"opencli-mcp": "0.0.22", "opencli": "1.8.8", "tikhub": "2.1.2"},
    )
    with httpx.Client(transport=httpx.MockTransport(_transport)) as client:
        result = check_updates(settings, client=client)
    rows = {row["provider"]: row for row in result.data["provider_updates"]}
    assert result.ok and result.data["soota_version"] == "0.1.0"
    assert rows["opencli-mcp"]["package_update_available"] is True
    assert rows["opencli"]["package_update_available"] is False
    assert rows["opencli"]["branch_relation_to_installed_tag"] == "ahead"
    assert rows["tikhub"]["branch_relation_to_installed_tag"] == "diverged"
    assert rows["tikhub"]["package_update_available"] is False


def test_updates_check_reports_partial_failure_without_claiming_current(settings, monkeypatch):
    monkeypatch.setattr(
        "soota.updates._installed_versions",
        lambda settings: {"opencli-mcp": "0.0.22", "opencli": "1.8.8", "tikhub": "2.1.2"},
    )

    def broken(request: httpx.Request) -> httpx.Response:
        if "opencli-mcp" in str(request.url) and "github.com" in str(request.url):
            return httpx.Response(403)
        return _transport(request)

    with httpx.Client(transport=httpx.MockTransport(broken)) as client:
        result = check_updates(settings, client=client)
    rows = {row["provider"]: row for row in result.data["provider_updates"]}
    assert not result.ok and result.status == "partial" and result.exit_code == 2
    assert rows["opencli-mcp"]["branch_relation_to_installed_tag"] == "unknown"
    assert rows["tikhub"]["latest_package_version"] == "2.1.2"


def test_updates_cli_json_and_text(settings, monkeypatch):
    monkeypatch.setattr(
        "soota.updates._installed_versions",
        lambda settings: {"opencli-mcp": "0.0.22", "opencli": "1.8.8", "tikhub": "2.1.2"},
    )
    with httpx.Client(transport=httpx.MockTransport(_transport)) as client:
        monkeypatch.setattr("soota.updates_cli.check_updates", lambda settings: check_updates(settings, client=client))
        runner = CliRunner()
        structured = runner.invoke(app, ["updates", "check", "--json"])
        readable = runner.invoke(app, ["updates", "check"])
    assert structured.exit_code == readable.exit_code == 0
    assert len(json.loads(structured.stdout)["data"]["provider_updates"]) == 3
    assert "opencli-mcp: 已装 0.0.22" in readable.stdout
