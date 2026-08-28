from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from soota.errors import TranscriptError


def ensure_audio(path: Path, ffmpeg: str = "ffmpeg") -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise TranscriptError("音频文件不存在或为空。", hint="删除缓存后重新 ingest。")
    suffix = path.suffix.lower()
    if suffix in {".m4a", ".mp3", ".wav", ".webm", ".ogg", ".flac"}:
        return path
    if shutil.which(ffmpeg) is None:
        raise TranscriptError(
            "需要 ffmpeg 才能从媒体容器抽出音频。",
            hint="brew install ffmpeg",
        )
    dest = path.with_suffix(".m4a")
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(path), "-vn", "-acodec", "aac", str(dest)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not dest.is_file():
        raise TranscriptError(
            "ffmpeg 抽音频失败。",
            hint=result.stderr[-400:] if result.stderr else "检查媒体文件。",
        )
    return dest


def fetch_audio_ytdlp(page_url: str, dest: Path, binary: str = "yt-dlp") -> Path:
    if shutil.which(binary) is None and not Path(binary).exists():
        raise TranscriptError(
            "需要 yt-dlp 作为本地音频回退。",
            hint="brew install yt-dlp",
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    template = str(dest.with_suffix("")) + ".%(ext)s"
    result = subprocess.run(
        [
            binary,
            "--no-playlist",
            "--no-progress",
            "-f",
            "bestaudio/best",
            "-x",
            "--audio-format",
            "m4a",
            "--force-overwrites",
            "-o",
            template,
            page_url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    produced = dest.with_suffix(".m4a")
    if result.returncode != 0 or not produced.is_file() or produced.stat().st_size == 0:
        raise TranscriptError(
            "yt-dlp 拉音频失败。",
            hint=(result.stderr or result.stdout or "检查链接、网络或 cookies。")[-400:],
        )
    if produced != dest:
        produced.replace(dest)
    return dest
