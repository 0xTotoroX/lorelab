from __future__ import annotations

from pathlib import Path

from soota.config import SootaSettings
from soota.errors import TranscriptError
from soota.models import (
    CaptionResult,
    MediaItem,
    TranscriptDocument,
    TranscriptMode,
    TranscriptSource,
    TranscriptStatus,
)
from soota.providers.tikhub.client import TikHubProvider
from soota.storage.cache import CacheStore
from soota.transcripts.asr import AsrEngine, resolve_engine
from soota.transcripts.download import ensure_audio


class TranscriptResolver:
    def __init__(
        self,
        provider: TikHubProvider,
        cache: CacheStore,
        settings: SootaSettings,
        asr: AsrEngine | None = None,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.settings = settings
        self.asr = asr

    def resolve(self, item: MediaItem, mode: TranscriptMode) -> TranscriptDocument:
        cached = self.cache.get_json(item.source, "transcript")
        if cached:
            document = TranscriptDocument.model_validate(cached)
            document.cache_hit = True
            return document

        if mode is TranscriptMode.NONE:
            document = TranscriptDocument(status=TranscriptStatus.MISSING, source=None, language=None, segments=[])
            self.cache.put_json(item.source, "transcript", document.model_dump(mode="json"))
            return document

        captions: CaptionResult | None = None
        if mode in {TranscriptMode.AUTO, TranscriptMode.CAPTIONS_ONLY}:
            captions = self.provider.get_captions(item)
            if captions.status is TranscriptStatus.READY and captions.segments:
                document = TranscriptDocument(
                    status=TranscriptStatus.READY,
                    source=captions.source,
                    language=captions.language,
                    segments=captions.segments,
                )
                self.cache.put_json(item.source, "transcript", document.model_dump(mode="json"))
                return document
            if mode is TranscriptMode.CAPTIONS_ONLY:
                document = TranscriptDocument(status=TranscriptStatus.MISSING, source=None, language=None, segments=[])
                self.cache.put_json(item.source, "transcript", document.model_dump(mode="json"))
                return document

        if mode is TranscriptMode.ASR or mode is TranscriptMode.AUTO:
            document = self._run_asr(item)
            self.cache.put_json(item.source, "transcript", document.model_dump(mode="json"))
            return document

        raise TranscriptError("未知字幕模式。")

    def _run_asr(self, item: MediaItem) -> TranscriptDocument:
        audio = self.provider.get_audio(item)
        media = ensure_audio(Path(audio.path))
        engine = self.asr or resolve_engine(self.settings.asr)
        segments = engine.transcribe(media, language=item.language or self.settings.default_language)
        return TranscriptDocument(
            status=TranscriptStatus.READY,
            source=TranscriptSource.ASR,
            language=item.language or self.settings.default_language,
            segments=segments,
        )
