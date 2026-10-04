from __future__ import annotations

from typing import Protocol

from soota.models import AudioAsset, CapabilitySet, CaptionAcquisition, CatalogPage, MediaItem, RequestRecord, SourceRef


class AudioProvider(Protocol):
    name: str
    records: list[RequestRecord]

    def get_audio(self, item: MediaItem) -> AudioAsset: ...


class CaptionProvider(Protocol):
    def get_captions(self, item: MediaItem) -> CaptionAcquisition: ...

    def cache_captions(self, item: MediaItem, result: CaptionAcquisition) -> None: ...


class Provider(Protocol):
    name: str

    def recognize(self, url: str) -> SourceRef | None: ...

    def capabilities(self, source: SourceRef) -> CapabilitySet: ...

    def inspect(self, source: SourceRef) -> MediaItem: ...

    def list_items(self, source: SourceRef, cursor: str | None = None, *, page_size: int = 100) -> CatalogPage: ...

    def get_captions(self, item: MediaItem) -> CaptionAcquisition: ...

    def cache_captions(self, item: MediaItem, result: CaptionAcquisition) -> None: ...

    def get_audio(self, item: MediaItem) -> AudioAsset: ...

    def estimate_requests(self, source: SourceRef, *, need_captions: bool, need_audio: bool) -> list[str]: ...
