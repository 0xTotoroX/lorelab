"""Compatibility imports for the renamed yt-dlp provider."""

from soota.providers.ytdlp import YtDlpProvider as SootaProvider
from soota.providers.ytdlp import capabilities_for, parse_json3, select_track

__all__ = ["SootaProvider", "capabilities_for", "parse_json3", "select_track"]
