import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from soota.providers.opencli_patches import XIAOHONGSHU_FILTERS, apply_managed_fixes

RELATIVE = "node_modules/@jackwener/opencli/clis/xiaohongshu/search.js"
FIXTURE = Path(__file__).parents[1] / "fixtures/opencli_xiaohongshu_filters.js"


def source_tree(tmp_path):
    path = tmp_path / RELATIVE
    path.parent.mkdir(parents=True)
    path.write_bytes(FIXTURE.read_bytes())
    license_path = path.parents[2] / "LICENSE"
    license_path.write_text("synthetic upstream license preserved")
    return path, license_path


def test_filter_patch_behavior_against_original_function(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for JavaScript behavior regression")
    path, _ = source_tree(tmp_path)
    harness = Path(__file__).parents[1] / "fixtures/xiaohongshu_filter_harness.js"
    script = tmp_path / "check.mjs"
    for patched in (False, True):
        if patched:
            apply_managed_fixes(tmp_path)
        script.write_text(path.read_text() + f"\nconst PATCHED = {str(patched).lower()};\n" + harness.read_text())
        result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


def test_filter_patch_idempotence_manifest_and_license(tmp_path):
    path, license_path = source_tree(tmp_path)
    apply_managed_fixes(tmp_path)
    first = path.read_bytes()
    manifest_path = tmp_path / "soota-compatibility.json"
    manifest_bytes = manifest_path.read_bytes()
    apply_managed_fixes(tmp_path)
    assert path.read_bytes() == first and manifest_path.read_bytes() == manifest_bytes
    assert license_path.read_text() == "synthetic upstream license preserved"
    manifest = json.loads(manifest_bytes)
    assert manifest["patches"] == ["xiaohongshu-search-filter-options"]
    assert manifest["files"] == [{"file": RELATIVE, "sha256": hashlib.sha256(first).hexdigest()}]
    assert manifest["soota_modification_license"] == "GPL-3.0-only"
    assert manifest["upstream_sources"]["xiaohongshu-search-filter-options"][-1].endswith("/2563")


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("change", ["drift", "duplicate", "partial", "function-drift"])
def test_filter_patch_skips_drift_and_nonunique_or_partial_anchors(tmp_path, which, change):
    path, _ = source_tree(tmp_path)
    old, new = XIAOHONGSHU_FILTERS[which]
    source = path.read_text()
    if change == "drift":
        source = source.replace(old, "// changed upstream")
    elif change == "duplicate":
        source += "\n" + old
    elif change == "partial":
        source = source.replace(old, new)
    else:
        source = source.replace("function buildApplySearchFiltersJs(requestedFilters)", "function changed(filters)")
    path.write_text(source)
    apply_managed_fixes(tmp_path)
    assert path.read_text() == source
    assert not (tmp_path / "soota-compatibility.json").exists()
