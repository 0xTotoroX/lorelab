from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import tikhub

from soota.config import AsrConfig, SootaSettings, TikHubConfig

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def block_browser_commands(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must stub OpenCLI; never use the user's browser.")

    monkeypatch.setattr("soota.providers.opencli.OpenCLIProvider._run", blocked)
    monkeypatch.setenv("OPENCLI_PROFILE", "test-context")
    monkeypatch.setattr("soota.providers.opencli_context.profile_config", lambda: {})


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> SootaSettings:
    return SootaSettings(
        output_dir=tmp_path / "out",
        default_language="zh",
        config_dir=tmp_path / "config",
        cache_dir=tmp_path / "cache",
        data_dir=tmp_path / "data",
        tikhub=TikHubConfig(),
        asr=AsrConfig(engine="whisper-cli", model="base"),
    )


@pytest.fixture
def sdk_transport(monkeypatch):
    """Keep the real SDK's serialization, errors and retries; replace only its HTTP transport."""
    original = tikhub.TikHub
    clients = []

    def install(handler):
        def create(**kwargs):
            client = original(**kwargs, transport=httpx.MockTransport(handler))
            clients.append(client)
            return client

        monkeypatch.setattr(tikhub, "TikHub", create)

    yield install
    for client in clients:
        client.close()
