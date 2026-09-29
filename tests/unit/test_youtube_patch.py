import json
import shutil
import subprocess

import pytest

from soota.providers.opencli_patches import YOUTUBE_TIMEDTEXT_FILTERS, apply_managed_fixes

RELATIVE = "node_modules/@jackwener/opencli/clis/youtube/transcript.js"


def fixture_source():
    first, second, third = [old for old, _ in YOUTUBE_TIMEDTEXT_FILTERS]
    return (
        """
const videoId = 'Example0001';
function timedtextUrlMatchesVideo(url) {
    return new URL(url).searchParams.get('v') === videoId;
}
function capture(url) {
    if (!url.includes('/api/timedtext')) return false;
"""
        + first
        + """
    if (!timedtextUrlMatchesVideo(url)) return false;
    return true;
}
function resources(urls) {
    return urls.filter(url => url.includes('/api/timedtext')
"""
        + second
        + """
}
function hook(url) {
    if (!url || !url.includes('/api/timedtext')) return false;
    if (!url.includes('fmt=json3')) return false;
"""
        + third
        + """
    return true;
}
"""
    )


def write_fixture(tmp_path):
    path = tmp_path / RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(fixture_source())
    return path


def test_patch_accepts_caption_urls_with_or_without_pot_and_keeps_video_scope(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for the managed JavaScript runtime regression")
    path = write_fixture(tmp_path)
    script = tmp_path / "check.mjs"
    checks = """
import assert from 'node:assert/strict';
const valid = 'https://www.youtube.com/api/timedtext?v=Example0001&fmt=json3&lang=zh';
for (const filter of [capture, url => resources([url]).length === 1, hook]) {
    assert.equal(filter(valid), EXPECT_NO_POT);
    assert.equal(filter(valid + '&pot=token'), true);
    assert.equal(filter(valid.replace('Example0001', 'Example0002') + '&pot=token'), false);
    assert.equal(filter(valid.replace('Example0001', 'Example0001suffix')), false);
    assert.equal(filter(valid.replace('json3', 'srv3')), false);
    assert.equal(filter(valid.replace('/api/timedtext', '/watch')), false);
}
"""
    for patched in (False, True):
        if patched:
            apply_managed_fixes(tmp_path)
        script.write_text(path.read_text() + checks.replace("EXPECT_NO_POT", str(patched).lower()))
        result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "soota-compatibility.json").read_text())
    assert manifest["patches"] == ["youtube-timedtext-optional-pot"]
    assert manifest["files"][0]["file"] == RELATIVE


def test_patch_is_idempotent(tmp_path):
    path = write_fixture(tmp_path)
    apply_managed_fixes(tmp_path)
    original = path.read_bytes()
    manifest = (tmp_path / "soota-compatibility.json").read_bytes()
    apply_managed_fixes(tmp_path)
    assert path.read_bytes() == original
    assert (tmp_path / "soota-compatibility.json").read_bytes() == manifest


@pytest.mark.parametrize("change", ["drift", "duplicate"])
def test_patch_skips_entire_transcript_when_any_capture_path_does_not_match(tmp_path, change):
    path = write_fixture(tmp_path)
    first = YOUTUBE_TIMEDTEXT_FILTERS[0][0]
    altered = path.read_text().replace(first, "// changed upstream") if change == "drift" else path.read_text() + first
    path.write_text(altered)
    apply_managed_fixes(tmp_path)
    assert path.read_text() == altered
    assert not (tmp_path / "soota-compatibility.json").exists()
