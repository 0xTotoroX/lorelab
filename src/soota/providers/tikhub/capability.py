from __future__ import annotations

from soota.models import CapabilitySet, SourceRef

# MVP: YouTube and Bilibili single-item inspect/captions/audio.
# Catalog/pagination stay false until M5.
PLATFORM_CAPABILITIES: dict[str, dict[str, CapabilitySet]] = {
    "youtube": {
        "video": CapabilitySet(inspect=True, captions=True, audio=True),
        "channel": CapabilitySet(inspect=False, catalog=True, pagination=True),
        "playlist": CapabilitySet(inspect=False, catalog=True, pagination=True),
    },
    "bilibili": {
        "video": CapabilitySet(inspect=True, captions=True, audio=True),
        "user": CapabilitySet(inspect=False, catalog=True, pagination=True),
        "shortlink": CapabilitySet(inspect=True, captions=True, audio=True),
    },
}


def capabilities_for(source: SourceRef) -> CapabilitySet:
    by_kind = PLATFORM_CAPABILITIES.get(source.platform, {})
    return by_kind.get(source.kind, CapabilitySet())
