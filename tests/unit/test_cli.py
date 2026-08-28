import json

from typer.testing import CliRunner

from soota.cli import app

runner = CliRunner()


def test_doctor_json_and_no_secret(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "supersecret-key-value")
    monkeypatch.setenv("SOOTA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SOOTA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SOOTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOOTA_OUTPUT_DIR", str(tmp_path / "out"))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["api_key_present"] is True
    assert "supersecret-key-value" not in result.stdout
    assert "supersecret-key-value" not in result.stderr


def test_inspect_offline_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOOTA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SOOTA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SOOTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOOTA_OUTPUT_DIR", str(tmp_path / "out"))
    result = runner.invoke(
        app,
        ["inspect", "https://www.bilibili.com/video/BV1M1421t7hT", "--offline", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["source"]["id"] == "BV1M1421t7hT"
    # stdout is a single JSON document
    json.loads(result.stdout)


def test_jobs_list_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOOTA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SOOTA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SOOTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOOTA_OUTPUT_DIR", str(tmp_path / "out"))
    result = runner.invoke(app, ["jobs", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "jobs" in payload["data"]
