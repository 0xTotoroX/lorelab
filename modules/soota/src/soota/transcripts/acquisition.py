from __future__ import annotations

from soota.models import CaptionAcquisition, CaptionResult, MediaItem, TranscriptStatus
from soota.providers.base import CaptionProvider
from soota.transcripts.conversion import convert_captions


def acquire_captions(provider: CaptionProvider, item: MediaItem) -> CaptionResult:
    """Orchestrate acquisition, pure conversion, then validated-body caching."""
    acquired = provider.get_captions(item)
    result = convert_captions(acquired)
    if isinstance(acquired, CaptionAcquisition) and not acquired.cache_hit and result.status == TranscriptStatus.READY:
        provider.cache_captions(item, acquired)
    if isinstance(acquired, CaptionAcquisition) and acquired.payload is not None:
        item.provenance["caption_format"] = acquired.payload.format
    return result
