import json
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize("relative", [False, True])
def test_missing_local_model_fails_before_cli_without_exposing_path(monkeypatch, tmp_path, relative) -> None:
    monkeypatch.chdir(tmp_path)
    model = "./private-model-missing" if relative else str(tmp_path / "private-model-missing")
    monkeypatch.setattr("soota.transcripts.asr.shutil.which", lambda _: "synthetic-mlx")
    monkeypatch.setattr("soota.transcripts.asr.subprocess.run", lambda *a, **k: pytest.fail("must not invoke MLX"))
    engine = MlxWhisperEngine(AsrConfig(mlx_model_path=model))
    with pytest.raises(TranscriptError, match="本地模型目录缺失") as caught:
        engine.transcribe(tmp_path / "audio.wav", language=None)
    assert caught.value.details == {"reason": "local_model_missing", "dispatched": False}
    assert "asr.mlx_model_path" in caught.value.hint
    assert "private-model-missing" not in json.dumps(caught.value.to_dict())


@pytest.mark.parametrize("files", [[], ["config.json"], ["weights.npz"], ["config.json", "unrelated.bin"]])
def test_incomplete_local_model_does_not_invoke_cli(monkeypatch, tmp_path, files) -> None:
    model = tmp_path / "model"
    model.mkdir()
    for name in files:
        (model / name).write_text("synthetic")
    monkeypatch.setattr("soota.transcripts.asr.shutil.which", lambda _: "synthetic-mlx")
    monkeypatch.setattr("soota.transcripts.asr.subprocess.run", lambda *a, **k: pytest.fail("must not invoke MLX"))
    with pytest.raises(TranscriptError, match="模型文件不完整") as caught:
        MlxWhisperEngine(AsrConfig(mlx_model_path=str(model))).transcribe(tmp_path / "audio.wav", language=None)
    assert caught.value.details == {"reason": "local_model_incomplete", "dispatched": False}


@pytest.mark.parametrize("model_kind", ["local-npz", "local-safetensors", "repo-id"])
def test_valid_local_model_and_explicit_repo_id_keep_cli_contract(monkeypatch, tmp_path, model_kind) -> None:
    model = "synthetic-org/whisper-tiny-mlx"
    if model_kind.startswith("local-"):
        directory = tmp_path / "model"
        directory.mkdir()
        (directory / "config.json").write_text("{}")
        (directory / ("weights." + model_kind.removeprefix("local-"))).write_bytes(b"synthetic weights")
        model = str(directory)
    calls = []
    monkeypatch.setattr("soota.transcripts.asr.shutil.which", lambda _: "synthetic-mlx")

    def run(cmd, **kwargs):
        calls.append(cmd)
        folder = Path(cmd[cmd.index("--output-dir") + 1])
        (folder / "transcript.json").write_text('{"segments": [{"start": 0, "end": 1, "text": "Synthetic"}]}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("soota.transcripts.asr.subprocess.run", run)
    result = MlxWhisperEngine(AsrConfig(mlx_model_path=model)).transcribe(tmp_path / "audio.wav", language="en")
    assert result.body["segments"][0]["text"] == "Synthetic"
    assert len(calls) == 1 and calls[0][calls[0].index("--model") + 1] == model
