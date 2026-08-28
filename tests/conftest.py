from __future__ import annotations

import json
from pathlib import Path

import pytest

from soota.config import AsrConfig, SootaSettings, TikHubConfig

FIXTURES = Path(__file__).parent / "fixtures"


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
