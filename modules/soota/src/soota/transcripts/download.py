"""Compatibility entry points backed by the shared, verified media service."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from soota.config import SootaSettings, load_settings
from soota.errors import InputError
from soota.media import MediaService


def ensure_audio(path: Path, ffmpeg: str = "ffmpeg", *, settings: SootaSettings | None = None) -> Path:
    if ffmpeg != "ffmpeg":
        raise InputError("共享媒体处理使用 PATH 中的 ffmpeg；请通过 PATH 选择程序。")
    return MediaService(settings or load_settings()).from_file(path, kind="audio").path


def fetch_audio_ytdlp(page_url: str, dest: Path, binary: str = "yt-dlp") -> Path:
    settings = load_settings()
    settings.local.binary = binary
    asset = MediaService(settings).from_page(page_url, kind="audio")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".audio-", dir=dest.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            with asset.path.open("rb") as source:
                shutil.copyfileobj(source, handle)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(dest)
    finally:
        temporary.unlink(missing_ok=True)
    return dest
