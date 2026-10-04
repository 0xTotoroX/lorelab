import json
from pathlib import Path

import pytest

from soota.config import AsrConfig, load_settings
from soota.errors import TranscriptError
from soota.models import TranscriptSource
from soota.transcripts.asr import MlxWhisperEngine, WhisperCliEngine, resolve_engine
from soota.transcripts.conversion import parse_payload


def cli_fixture(tmp_path: Path, body: str) -> Path:
    binary = tmp_path / "mlx_whisper"
    binary.write_text("#!/usr/bin/env python3\nimport json, pathlib, sys\n" + body)
    binary.chmod(0o755)
    return binary


def test_mlx_cli_contract_and_temporary_output_cleanup(tmp_path) -> None:
    marker = tmp_path / "invocation.json"
    binary = cli_fixture(
        tmp_path,
        "args = sys.argv[1:]\n"
        "assert args[args.index('--model') + 1] == 'mlx-community/whisper-base-mlx'\n"
        "assert args[args.index('--best-of') + 1] == 'None'\n"
        "assert args[args.index('--language') + 1] == 'zh'\n"
        "assert args[args.index('--task') + 1] == 'transcribe'\n"
        "folder = pathlib.Path(args[args.index('--output-dir') + 1])\n"
        f"pathlib.Path({str(marker)!r}).write_text(json.dumps({{'folder': str(folder)}}))\n"
        "(folder / 'transcript.json').write_text(json.dumps({'segments': "
        "[{'start': 0.125, 'end': 1.25, 'text': '中文转写'}]}))\n",
    )
    engine = resolve_engine(AsrConfig(engine="mlx-whisper", mlx_whisper_bin=str(binary)))
    assert isinstance(engine, MlxWhisperEngine)
    segments = parse_payload(
        engine.transcribe(tmp_path / "audio.wav", language="zh-CN"), language="zh-CN", source=TranscriptSource.ASR
    )
    assert [(s.segment_id, s.start_ms, s.end_ms, s.text, s.source) for s in segments] == [
        ("seg-000001", 125, 1250, "中文转写", TranscriptSource.ASR)
    ]
    assert not Path(json.loads(marker.read_text())["folder"]).exists()


def test_success_exit_without_json_does_not_reuse_old_output(tmp_path) -> None:
    stale = tmp_path / "asr"
    stale.mkdir()
    (stale / "audio.json").write_text('{"segments": [{"start": 0, "end": 1, "text": "old"}]}')
    binary = cli_fixture(tmp_path, "sys.exit(0)\n")
    engine = MlxWhisperEngine(AsrConfig(mlx_whisper_bin=str(binary)))
    with pytest.raises(TranscriptError, match="转写失败"):
        engine.transcribe(tmp_path / "audio.wav", language=None)


def test_private_mlx_settings_and_explicit_cli_fallback(monkeypatch, tmp_path) -> None:
    (tmp_path / "config.toml").write_text(
        '[asr]\nengine = "mlx-whisper"\nmodel = "base"\n'
        'mlx_whisper_bin = "/path/to/mlx_whisper"\nmlx_model_path = "/path/to/model"\n'
    )
    monkeypatch.setenv("SOOTA_CONFIG_DIR", str(tmp_path))
    settings = load_settings(ignore_payment=True)
    assert settings.asr.model == "base"
    assert settings.asr.mlx_model_path == "/path/to/model"
    assert isinstance(resolve_engine(settings.asr), MlxWhisperEngine)
    assert isinstance(resolve_engine(AsrConfig(engine="whisper-cli")), WhisperCliEngine)
