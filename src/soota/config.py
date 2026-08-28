from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, Field

APP_NAME = "Soota"
APP_AUTHOR = "soota"


class AsrConfig(BaseModel):
    engine: str = "auto"
    model: str = "base"
    device: str = "cpu"
    whisper_bin: str = "whisper"


class TikHubConfig(BaseModel):
    base_url: str = "https://api.tikhub.io"
    timeout_seconds: float = 60.0


class SootaSettings(BaseModel):
    output_dir: Path = Field(default_factory=lambda: Path.home() / "Documents" / "Soota")
    default_language: str = "zh"
    config_dir: Path
    cache_dir: Path
    data_dir: Path
    tikhub: TikHubConfig = Field(default_factory=TikHubConfig)
    asr: AsrConfig = Field(default_factory=AsrConfig)

    @property
    def config_path(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "ledger.jsonl"


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def default_dirs() -> tuple[Path, Path, Path]:
    # Plan pins config to ~/.config/soota; cache/jobs follow macOS app dirs.
    config_dir = _env_path("SOOTA_CONFIG_DIR") or Path.home() / ".config" / "soota"
    cache_dir = _env_path("SOOTA_CACHE_DIR") or Path(platformdirs.user_cache_dir(APP_NAME, APP_AUTHOR))
    data_dir = _env_path("SOOTA_DATA_DIR") or Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    return config_dir, cache_dir, data_dir


def load_settings() -> SootaSettings:
    config_dir, cache_dir, data_dir = default_dirs()
    path = config_dir / "config.toml"
    data: dict[str, Any] = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    soota = data.get("soota", data)
    output = _env_path("SOOTA_OUTPUT_DIR")
    settings = SootaSettings(
        output_dir=output or Path(soota.get("output_dir", Path.home() / "Documents" / "Soota")).expanduser(),
        default_language=str(soota.get("default_language", "zh")),
        config_dir=config_dir,
        cache_dir=cache_dir,
        data_dir=data_dir,
        tikhub=TikHubConfig(
            base_url=str((data.get("tikhub") or {}).get("base_url", "https://api.tikhub.io")),
            timeout_seconds=float((data.get("tikhub") or {}).get("timeout_seconds", 60.0)),
        ),
        asr=AsrConfig(
            engine=str((data.get("asr") or {}).get("engine", "auto")),
            model=str((data.get("asr") or {}).get("model", "base")),
            device=str((data.get("asr") or {}).get("device", "cpu")),
            whisper_bin=str((data.get("asr") or {}).get("whisper_bin", "whisper")),
        ),
    )
    return settings


def ensure_dirs(settings: SootaSettings) -> None:
    for path in (settings.config_dir, settings.cache_dir, settings.data_dir, settings.jobs_dir, settings.output_dir):
        path.mkdir(parents=True, exist_ok=True)
