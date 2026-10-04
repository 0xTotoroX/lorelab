"""Compatibility imports for the renamed yt-dlp provider."""

from soota.providers.ytdlp import YtDlpProvider as SootaProvider
from soota.providers.ytdlp import capabilities_for, select_track

__all__ = ["SootaProvider", "capabilities_for", "select_track"]
