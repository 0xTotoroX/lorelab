from __future__ import annotations

from typing import Protocol

from soota.models import AudioAsset, CapabilitySet, CaptionResult, MediaItem, SourceRef


class Provider(Protocol):
    name: str

    def recognize(self, url: str) -> SourceRef | None: ...

    def capabilities(self, source: SourceRef) -> CapabilitySet: ...

    def inspect(self, source: SourceRef) -> MediaItem: ...

    def get_captions(self, item: MediaItem) -> CaptionResult: ...

    def get_audio(self, item: MediaItem) -> AudioAsset: ...

    def estimate_requests(self, source: SourceRef, *, need_captions: bool, need_audio: bool) -> list[str]: ...
