import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from soota.errors import ContractError, TranscriptError
from soota.models import MediaItem
from soota.providers.downie import DownieProvider, DownloadPending
from soota.providers.process import ProcessResult
from soota.routing import recognize

URL = "https://www.youtube.com/watch?v=--Example01"


def item():
    return MediaItem(source=recognize(URL))


def setup_runner(monkeypatch, *, complete=True, has_audio=True):
    calls = []
    folders = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "open":
            params = parse_qs(urlparse(argv[-1]).query)
            assert params["url"] == [URL]
            assert "postprocessing" not in params  # The configured custom hook supplies the receipt.
            folder = Path(params["destination"][0])
            folders.append(folder)
            if complete:
                path = folder / "example.webm"
                path.write_bytes(b"downloaded-media")
                (folder / "complete.path").write_text(str(path))
            return ProcessResult(0, "", "")
        if argv[0] == "ffprobe":
            return ProcessResult(0, json.dumps({"streams": [{"codec_type": "audio" if has_audio else "video"}]}), "")
        if argv[0] == "ffmpeg":
            Path(argv[-1]).write_bytes(b"converted-audio")
            return ProcessResult(0, "", "")
        pytest.fail(str(argv))

    monkeypatch.setattr(DownieProvider, "_preflight", lambda self: None)
    monkeypatch.setattr("soota.providers.downie.run_process", run)
    return calls, folders


def test_downie_waits_for_receipt_and_caches_audio(settings, monkeypatch):
    calls, folders = setup_runner(monkeypatch)
    provider = DownieProvider(settings)
    result = provider.get_audio(item())
    assert result.path.read_bytes() == b"converted-audio"
    assert [call[0] for call in calls] == ["open", "ffprobe", "ffmpeg"]
    assert provider.get_audio(item()).path == result.path
    assert len(calls) == 3 and provider.records[-1].cache_hit
    assert folders[0].name.startswith("soota-downie-")


def test_pending_download_resumes_without_resubmitting(settings, monkeypatch):
    calls, folders = setup_runner(monkeypatch, complete=False)
    settings.audio.timeout_seconds = 0.01
    with pytest.raises(DownloadPending):
        DownieProvider(settings).get_audio(item())
    path = folders[0] / "finished.webm"
    path.write_bytes(b"finished")
    (folders[0] / "complete.path").write_text(str(path))
    assert DownieProvider(settings).get_audio(item()).path.is_file()
    assert sum(call[0] == "open" for call in calls) == 1


def test_file_without_receipt_does_not_count_as_complete(settings, monkeypatch):
    setup_runner(monkeypatch, complete=False)
    settings.audio.timeout_seconds = 0.01
    provider = DownieProvider(settings)
    folder = provider._submit_or_resume(item())
    (folder / "looks-finished.m4a").write_bytes(b"partial")
    with pytest.raises(DownloadPending):
        provider.get_audio(item())
    assert not provider.cache.audio_path(item().source).exists()


def test_receipt_cannot_read_a_file_outside_task(settings, monkeypatch, tmp_path):
    setup_runner(monkeypatch, complete=False)
    provider = DownieProvider(settings)
    folder = provider._submit_or_resume(item())
    other = tmp_path / "private.m4a"
    other.write_bytes(b"other-file")
    (folder / "complete.path").write_text(str(other))
    with pytest.raises(ContractError):
        provider.get_audio(item())


def test_media_without_audio_is_not_sent_to_asr(settings, monkeypatch):
    calls, _ = setup_runner(monkeypatch, has_audio=False)
    with pytest.raises(TranscriptError):
        DownieProvider(settings).get_audio(item())
    assert not any(call[0] == "ffmpeg" for call in calls)


def test_callback_only_marks_requested_soota_tasks(tmp_path):
    hook = Path(__file__).parents[2] / "src/soota/providers/downie_complete.sh"
    unrelated = tmp_path / "ordinary-download"
    unrelated.mkdir()
    media = unrelated / "sample.wav"
    media.write_bytes(b"audio")
    subprocess.run(["/bin/sh", str(hook), str(media)], check=True)
    assert not (unrelated / "complete.path").exists()
    task = tmp_path / "soota-downie-test"
    task.mkdir()
    audio = task / "a file.wav"
    audio.write_bytes(b"audio")
    (task / "request.json").write_text("{}")
    subprocess.run(["/bin/sh", str(hook), str(audio)], check=True)
    assert (task / "complete.path").read_text() == str(audio)
    assert not (task / "complete.path.tmp").exists()
