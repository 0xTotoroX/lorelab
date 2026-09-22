from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any, Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from soota.errors import InputError

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


class OpenCLIConfig(BaseModel):
    binary: str | None = None
    profile: str | None = None
    timeout_seconds: float = Field(default=90, gt=0)
    max_output_bytes: int = Field(default=8_388_608, ge=1024)
    metadata_cache_seconds: int = Field(default=300, ge=0)


class PaymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["ask", "auto"] = "ask"
    min_balance_usd: FiniteFloat | None = Field(default=None, ge=0)
    default_provider: Literal["auto", "opencli", "tikhub"] = "auto"


class SootaSettings(BaseModel):
    output_dir: Path = Field(default_factory=lambda: Path.home() / "Documents" / "Soota")
    default_language: str = "zh"
    config_dir: Path
    cache_dir: Path
    data_dir: Path
    tikhub: TikHubConfig = Field(default_factory=TikHubConfig)
    opencli: OpenCLIConfig = Field(default_factory=OpenCLIConfig)
    payment: PaymentConfig = Field(default_factory=PaymentConfig)
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


def load_settings(*, ignore_payment: bool = False) -> SootaSettings:
    config_dir, cache_dir, data_dir = default_dirs()
    path = config_dir / "config.toml"
    data: dict[str, Any] = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    soota = data.get("soota", data)
    payment = dict((data.get("tikhub") or {}).get("billing") or {})
    payment["default_provider"] = (data.get("routing") or {}).get("default_provider", "auto")
    policy_path = config_dir / "payment-policy.json"
    try:
        if ignore_payment:
            payment = {}
        elif policy_path.is_file():
            saved = json.loads(policy_path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("expected policy object")
            payment.update(saved)
        payment_config = PaymentConfig.model_validate(payment)
    except (ValueError, TypeError, ValidationError) as exc:
        raise InputError("费用策略文件无效，未执行任何请求。", hint="使用 soota policy set --mode ask 恢复。") from exc
    output = _env_path("SOOTA_OUTPUT_DIR")
    settings = SootaSettings(
        output_dir=output or Path(soota.get("output_dir", Path.home() / "Documents" / "Soota")).expanduser(),
        default_language=str(soota.get("default_language", "zh")),
        config_dir=config_dir,
        cache_dir=cache_dir,
        data_dir=data_dir,
        payment=payment_config,
        tikhub=TikHubConfig(
            base_url=str((data.get("tikhub") or {}).get("base_url", "https://api.tikhub.io")),
            timeout_seconds=float((data.get("tikhub") or {}).get("timeout_seconds", 60.0)),
        ),
        opencli=OpenCLIConfig.model_validate(
            {
                **(data.get("opencli") or {}),
                **({"binary": os.environ["SOOTA_OPENCLI_BINARY"]} if os.environ.get("SOOTA_OPENCLI_BINARY") else {}),
                **({"profile": os.environ["OPENCLI_PROFILE"]} if os.environ.get("OPENCLI_PROFILE") else {}),
            }
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
