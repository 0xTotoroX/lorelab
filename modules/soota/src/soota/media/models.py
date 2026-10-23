from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MediaKind = Literal["video", "audio", "image"]


class MediaDescriptor(BaseModel):
    """In-memory acquisition description. Network credentials never enter artifacts."""

    model_config = ConfigDict(hide_input_in_errors=True)

    url: str | None = Field(default=None, exclude=True, repr=False)
    video_url: str | None = Field(default=None, exclude=True, repr=False)
    audio_url: str | None = Field(default=None, exclude=True, repr=False)
    path: Path | None = Field(default=None, exclude=True)
    source_provider: str = "http"
    headers: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)
    video_headers: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)
    audio_headers: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)
    protocol: Literal["auto", "http", "hls", "dash"] = "auto"
    identity: str | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def one_input(self) -> MediaDescriptor:
        if (
            sum((self.path is not None, self.url is not None, self.video_url is not None or self.audio_url is not None))
            != 1
        ):
            raise ValueError("Provide one local path, one URL, or a set of media track URLs.")
        return self


class MediaStream(BaseModel):
    index: int
    type: str
    codec: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    attached_picture: bool = False


class MediaVerification(BaseModel):
    decoded: bool = True
    expected_duration_seconds: float | None = None
    duration_checked: bool = False
    duration_tolerance_seconds: float | None = None
    completeness: Literal["duration_matched", "input_duration_matched", "source_duration_unknown"] = (
        "source_duration_unknown"
    )


class MediaAsset(BaseModel):
    path: Path
    kind: MediaKind
    format: str
    size: int
    sha256: str
    duration_seconds: float | None = None
    streams: list[MediaStream]
    verification: MediaVerification
    source_provider: str | None = None
    cache_hit: bool = False


def positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value))
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number > 0 else None
