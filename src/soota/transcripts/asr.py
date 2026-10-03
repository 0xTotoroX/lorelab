from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from soota.config import AsrConfig
from soota.errors import TranscriptError
from soota.models import TranscriptSegment, TranscriptSource
from soota.transcripts.captions import assign_ids


class AsrEngine(Protocol):
    name: str

    def transcribe(self, audio: Path, *, language: str | None) -> list[TranscriptSegment]: ...


class WhisperCliEngine:
    name = "whisper-cli"

    def __init__(self, config: AsrConfig) -> None:
        self.config = config

    def transcribe(self, audio: Path, *, language: str | None) -> list[TranscriptSegment]:
        binary = shutil.which(self.config.whisper_bin) or self.config.whisper_bin
        if not shutil.which(binary) and not Path(binary).exists():
            raise TranscriptError(
                "本机没有 whisper CLI。",
                hint="brew install openai-whisper，或把 asr.engine 设为 faster-whisper。大模型下载前会先停下来。",
            )
        work = audio.parent / "asr"
        work.mkdir(parents=True, exist_ok=True)
        cmd = [
            binary,
            str(audio),
            "--model",
            self.config.model,
            "--output_dir",
            str(work),
            "--output_format",
            "json",
            "--verbose",
            "False",
        ]
        if language:
            cmd.extend(["--language", _whisper_lang(language)])
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise TranscriptError(
                "whisper CLI 转写失败。",
                hint=result.stderr[-400:] if result.stderr else "检查模型是否已下载。默认使用 base，避免自动拉 turbo。",
            )
        json_path = work / f"{audio.stem}.json"
        if not json_path.is_file():
            matches = list(work.glob("*.json"))
            if not matches:
                raise TranscriptError("whisper 没有写出 JSON。")
            json_path = matches[0]
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return _segments_from_whisper(payload, language)


class FasterWhisperEngine:
    name = "faster-whisper"

    def __init__(self, config: AsrConfig) -> None:
        self.config = config

    def transcribe(self, audio: Path, *, language: str | None) -> list[TranscriptSegment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptError(
                "未安装 faster-whisper。",
                hint="uv sync --extra asr ，并确认模型已在本地，不要在未确认时下载大模型。",
            ) from exc
        model = WhisperModel(self.config.model, device=self.config.device)
        segments_iter, _info = model.transcribe(str(audio), language=_whisper_lang(language) if language else None)
        raw: list[TranscriptSegment] = []
        for item in segments_iter:
            text = (item.text or "").strip()
            if not text:
                continue
            raw.append(
                TranscriptSegment(
                    segment_id="seg-tmp",
                    start_ms=int(float(item.start) * 1000),
                    end_ms=int(float(item.end) * 1000),
                    text=text,
                    language=language,
                    source=TranscriptSource.ASR,
                )
            )
        if not raw:
            raise TranscriptError("faster-whisper 没有识别到语音。")
        return assign_ids(raw)


class MlxWhisperEngine:
    name = "mlx-whisper"

    def __init__(self, config: AsrConfig) -> None:
        self.config = config

    def transcribe(self, audio: Path, *, language: str | None) -> list[TranscriptSegment]:
        binary = shutil.which(self.config.mlx_whisper_bin)
        if not binary:
            raise TranscriptError("未找到 mlx_whisper CLI。", hint="安装 mlx-whisper，并配置 asr.mlx_whisper_bin。")
        model = self.config.mlx_model_path
        if not model:
            if self.config.model != "base":
                raise TranscriptError("MLX 非 base 模型需设置 asr.mlx_model_path。")
            model = "mlx-community/whisper-base-mlx"
        with tempfile.TemporaryDirectory(prefix="soota-mlx-") as folder:
            cmd = [
                binary,
                str(audio),
                "--model",
                model,
                "--output-dir",
                folder,
                "--output-name",
                "transcript",
                "--output-format",
                "json",
                "--verbose",
                "False",
                "--task",
                "transcribe",
                "--fp16",
                "True",
                "--best-of",
                "None",
            ]
            if language:
                cmd.extend(["--language", _whisper_lang(language)])
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            output = Path(folder) / "transcript.json"
            if result.returncode or not output.is_file():
                raise TranscriptError(
                    "MLX Whisper 转写失败。", hint="检查模型目录与 CLI；可设置 asr.engine=whisper-cli 回退。"
                )
            try:
                payload = json.loads(output.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise TranscriptError("MLX Whisper 没有生成有效 JSON。") from exc
            return _segments_from_whisper(payload, language)


def resolve_engine(config: AsrConfig) -> AsrEngine:
    engine = config.engine
    if engine == "mlx-whisper":
        return MlxWhisperEngine(config)
    if engine == "faster-whisper":
        return FasterWhisperEngine(config)
    if engine == "whisper-cli":
        return WhisperCliEngine(config)
    if shutil.which("whisper") or Path(config.whisper_bin).exists():
        return WhisperCliEngine(config)
    try:
        import faster_whisper  # noqa: F401

        return FasterWhisperEngine(config)
    except ImportError:
        return WhisperCliEngine(config)


def _whisper_lang(language: str) -> str:
    lowered = language.lower()
    if lowered.startswith("zh"):
        return "zh"
    if lowered.startswith("en"):
        return "en"
    return lowered.split("-")[0]


def _segments_from_whisper(payload: dict[str, object], language: str | None) -> list[TranscriptSegment]:
    items = payload.get("segments")
    if not isinstance(items, list):
        raise TranscriptError("whisper JSON 缺少 segments。")
    raw: list[TranscriptSegment] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = float(item.get("start") or 0)
        end = float(item.get("end") or start)
        raw.append(
            TranscriptSegment(
                segment_id="seg-tmp",
                start_ms=int(start * 1000),
                end_ms=int(end * 1000),
                text=text,
                language=language,
                source=TranscriptSource.ASR,
            )
        )
    if not raw:
        raise TranscriptError("whisper 结果没有文本。")
    return assign_ids(raw)
