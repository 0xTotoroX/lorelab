from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class TranscriptMode(StrEnum):
    AUTO = "auto"
    CAPTIONS_ONLY = "captions-only"
    ASR = "asr"
    NONE = "none"


class TranscriptSource(StrEnum):
    OFFICIAL = "official"
    AUTO = "auto"
    ASR = "asr"


class TranscriptStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    PENDING = "pending"


class AnalysisStatus(StrEnum):
    READY = "ready"
    PENDING = "pending"
    INVALID = "invalid"


class SourceRef(BaseModel):
    platform: str
    kind: str
    id: str
    url: str
    canonical_url: str

    @property
    def cache_identity(self) -> str:
        return f"{self.platform}:{self.kind}:{self.id}"


class CapabilitySet(BaseModel):
    inspect: bool = False
    captions: bool = False
    audio: bool = False
    catalog: bool = False
    pagination: bool = False
    article: bool = False


class MediaItem(BaseModel):
    source: SourceRef
    title: str | None = None
    creator: str | None = None
    published_at: datetime | None = None
    duration_seconds: int | None = None
    language: str | None = None
    extras: dict[str, str] = Field(default_factory=dict)


class CaptionTrack(BaseModel):
    language: str
    name: str | None = None
    kind: TranscriptSource = TranscriptSource.OFFICIAL


class TranscriptSegment(BaseModel):
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    language: str | None = None
    source: TranscriptSource


class TranscriptDocument(BaseModel):
    status: TranscriptStatus
    source: TranscriptSource | None = None
    language: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    cache_hit: bool = False


class CaptionResult(BaseModel):
    status: TranscriptStatus
    source: TranscriptSource | None = None
    language: str | None = None
    tracks: list[CaptionTrack] = Field(default_factory=list)
    segments: list[TranscriptSegment] = Field(default_factory=list)


class AudioAsset(BaseModel):
    path: Path
    mime: str | None = None
    duration_seconds: float | None = None


class KeyPoint(BaseModel):
    text: str
    evidence: list[str] = Field(default_factory=list)


class Chapter(BaseModel):
    title: str
    start_ms: int | None = None
    end_ms: int | None = None
    summary: str = ""


class Analysis(BaseModel):
    schema_version: int = 1
    summary: str
    key_points: list[KeyPoint] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    language: str | None = None


class RequestRecord(BaseModel):
    endpoint: str
    billed: bool
    cache_hit: bool = False
    estimated_cost_usd: float | None = None
    note: str | None = None


class TranscriptManifest(BaseModel):
    status: TranscriptStatus
    source: TranscriptSource | None = None
    language: str | None = None
    path: str | None = None
    segments: int = 0


class AnalysisManifest(BaseModel):
    status: AnalysisStatus = AnalysisStatus.PENDING
    path: str | None = None


class ProcessingManifest(BaseModel):
    provider: str = "tikhub"
    cache_hit: bool = False
    estimated_cost_usd: float | None = 0.0
    actual_cost_usd: float | None = 0.0
    request_count: int = 0
    price_basis: str | None = None
    warnings: list[str] = Field(default_factory=list)
    requests: list[RequestRecord] = Field(default_factory=list)


class ContentBundleManifest(BaseModel):
    schema_version: int = 1
    source: SourceRef
    metadata: dict[str, Any] = Field(default_factory=dict)
    transcript: TranscriptManifest
    analysis: AnalysisManifest = Field(default_factory=AnalysisManifest)
    processing: ProcessingManifest = Field(default_factory=ProcessingManifest)
    files: dict[str, str] = Field(default_factory=dict)

    def metadata_from_item(self, item: MediaItem) -> None:
        self.metadata = {
            "title": item.title,
            "creator": item.creator,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "duration_seconds": item.duration_seconds,
            "language": item.language,
        }


class CommandResult(BaseModel):
    ok: bool
    status: Literal["success", "partial", "error"]
    code: str
    exit_code: int
    message: str
    hint: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
