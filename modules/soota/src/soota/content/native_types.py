from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NativeEntry:
    url: str
    title: str
    raw: dict[str, Any]
    id: str | None = None


@dataclass
class NativeOperation:
    raw: Any
    provider: str
    operation: str
    workdir: Path
    files: list[Path] = field(default_factory=list)
    entries: list[NativeEntry] | None = None
    warnings: list[str] = field(default_factory=list)
    completeness: str = "unknown"

    @property
    def data(self) -> Any:
        return self.raw


@dataclass
class NativeContent:
    raw: Any
    body: str
    title: str
    source_url: str
    provider: str
    scope: str
    operation: str
    attachments: list[Path] = field(default_factory=list)
    format: str = "markdown"
    warnings: list[str] = field(default_factory=list)

    @property
    def data(self) -> Any:
        return self.raw


@dataclass
class NativeMedia:
    raw: Any
    files: list[Path]
    source_url: str
    provider: str
    operation: str
    warnings: list[str] = field(default_factory=list)
    verified: bool = False
