import pytest
from soota.config import AutoUpdateConfig, PaymentConfig, SootaSettings


@pytest.fixture
def settings(tmp_path):
    return SootaSettings(
        output_dir=tmp_path / "out",
        config_dir=tmp_path / "config",
        cache_dir=tmp_path / "cache",
        data_dir=tmp_path / "data",
        updates=AutoUpdateConfig(enabled=False),
        payment=PaymentConfig(mode="auto"),
    )


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("SOOTA_AUTO_UPDATE", "false")
    monkeypatch.setenv("OPENCLI_PROFILE", "test-context")
    monkeypatch.setattr("soota.providers.opencli_context.profile_config", dict)


@pytest.fixture
def article(tmp_path):
    path = tmp_path / "source.md"
    path.write_text("# Source title\n\nFirst paragraph.\n\nRepeated.\n\nRepeated.\n")
    return path
