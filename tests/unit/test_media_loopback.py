from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading

import pytest

from soota.media import MediaDescriptor, MediaService


@pytest.fixture
def loopback_media(tmp_path):
    if not all(shutil.which(name) for name in ("ffmpeg", "ffprobe", "yt-dlp")):
        pytest.skip("local yt-dlp and FFmpeg tools are needed")
    root = tmp_path / "server"
    root.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=25:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(root / "sample.mp4"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(root / "sample.mp4"),
            "-c",
            "copy",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            str(root / "sample.m3u8"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(root / "sample.mp4"),
            "-c",
            "copy",
            "-f",
            "dash",
            str(root / "sample.mpd"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    (root / "page.html").write_text(
        '<html><head><title>Sample</title></head><body><video src="sample.mp4"></video></body></html>'
    )
    requests = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            super().do_GET()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_real_ytdlp_page_download_and_resume_use_only_loopback(settings, loopback_media):
    base, requests = loopback_media
    settings.local.cookies_browser = ""
    service = MediaService(settings, timeout_seconds=30)
    first = service.from_page(base + "/page.html", expected_duration=2)
    count = len(requests)
    second = service.from_page(base + "/page.html", expected_duration=2)
    assert first.kind == "video" and first.verification.duration_checked
    assert second.cache_hit and len(requests) == count


@pytest.mark.parametrize("name,protocol", [("sample.m3u8", "hls"), ("sample.mpd", "dash")])
def test_real_manifest_descriptor_has_no_page_reextraction(settings, loopback_media, name, protocol):
    base, requests = loopback_media
    service = MediaService(settings, timeout_seconds=30)
    descriptor = MediaDescriptor(
        url=base + f"/{name}?signature=fixture-secret-token", protocol=protocol, source_provider="fixture"
    )
    result = service.from_descriptor(descriptor, expected_duration=2)
    assert result.kind == "video" and result.source_provider == "fixture"
    assert result.verification.duration_checked
    assert not any("page.html" in path for path in requests)
    assert "fixture-secret-token" not in result.model_dump_json()
