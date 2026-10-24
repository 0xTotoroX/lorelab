"""GitHub 分发适配的恢复/拒绝替换测试；不调用真实服务。"""

import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "publish_github", Path(__file__).resolve().parents[1] / "packaging/publish_github.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


@pytest.fixture
def release(tmp_path, monkeypatch):
    plugin = tmp_path / "lorelab-plugin-1.0.0-source-test.zip"
    with zipfile.ZipFile(plugin, "w") as archive:
        archive.writestr("lorelab/lorelab-binding.json", json.dumps({"version": "1.0.0",
            "source_fingerprint": "source-test", "components_lock_sha256": "c" * 64}))
    plugin.with_name(plugin.name + ".sha256").write_text(f"{publisher.digest(plugin)}  {plugin.name}\n")
    receipt = {"ok": True, "executed": True, "versions": {"soota": "1.0.0", "lorelab": "1.0.0"},
               "soota": {"repository": "git@github.com:example/soota.git", "commit": "a" * 40, "tag": "v1.0.0"},
               "lorelab": {"repository": "https://github.com/example/lorelab.git",
                           "commit": "b" * 40, "tag": "v1.0.0"}}
    state = {"releases": {}, "calls": [], "fail_upload": False, "lookup_error": False}
    monkeypatch.setattr(publisher, "source_identity", lambda _source: ("b" * 40, "source-test", "c" * 64))

    def gh(*args):
        args = list(map(str, args))
        state["calls"].append(args)
        if args[0] == "api":
            _, owner, name, operation, *_tail = args[1].split("/")
            key = owner + "/" + name
            if operation == "commits":
                return subprocess.CompletedProcess(args, 0, json.dumps({"sha": receipt[name]["commit"]}), "")
            if state["lookup_error"]:
                return subprocess.CompletedProcess(args, 1, '{"status":"503"}', "unavailable")
            if operation.startswith("releases?"):
                entries = [state["releases"][key]["value"]] if key in state["releases"] else []
                return subprocess.CompletedProcess(args, 0, json.dumps([entries]), "")
            if key not in state["releases"] or state["releases"][key]["value"]["draft"]:
                return subprocess.CompletedProcess(args, 1, '{"status":"404"}', "not found")
            return subprocess.CompletedProcess(args, 0, json.dumps(state["releases"][key]["value"]), "")
        action = args[1]
        repo = args[args.index("--repo") + 1]
        if action == "create":
            state["releases"][repo] = {"value": {"name": args[args.index("--title") + 1],
                "body": Path(args[args.index("--notes-file") + 1]).read_text(), "draft": True,
                "prerelease": False, "tag_name": "v1.0.0", "assets": [],
                "html_url": "https://github.com/" + repo}, "bytes": {}}
        elif action == "upload":
            if state["fail_upload"]:
                state["fail_upload"] = False
                return subprocess.CompletedProcess(args, 1, "", "synthetic upload failure")
            asset = Path(args[3])
            assert asset.name not in state["releases"][repo]["bytes"]
            state["releases"][repo]["bytes"][asset.name] = asset.read_bytes()
            state["releases"][repo]["value"]["assets"].append({"name": asset.name})
        elif action == "download":
            name = args[args.index("--pattern") + 1]
            (Path(args[args.index("--dir") + 1]) / name).write_bytes(state["releases"][repo]["bytes"][name])
        elif action == "edit":
            state["releases"][repo]["value"]["draft"] = False
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(publisher, "gh", gh)
    return receipt, tmp_path, state


def test_release_creation_and_repeat_have_no_duplicate_uploads(release):
    receipt, directory, state = release
    first = publisher.publish(receipt, directory, "Product notes", "Soota notes")
    second = publisher.publish(receipt, directory, "Product notes", "Soota notes")
    assert first == second
    assert sum(c[:2] == ["release", "create"] for c in state["calls"]) == 2
    assert sum(c[:2] == ["release", "upload"] for c in state["calls"]) == 2
    assert all(not r["value"]["draft"] for r in state["releases"].values())


def test_partial_asset_upload_resumes_existing_releases(release):
    receipt, directory, state = release
    state["fail_upload"] = True
    with pytest.raises(RuntimeError, match="upload failure"):
        publisher.publish(receipt, directory, "Product notes", "Soota notes")
    assert not state["releases"]["example/soota"]["value"]["draft"]
    assert state["releases"]["example/lorelab"]["value"]["draft"]
    assert publisher.publish(receipt, directory, "Product notes", "Soota notes")["ok"]
    assert sum(c[:2] == ["release", "create"] for c in state["calls"]) == 2


def test_changed_notes_do_not_replace_existing_release(release):
    receipt, directory, state = release
    publisher.publish(receipt, directory, "Product notes", "Soota notes")
    state["calls"].clear()
    with pytest.raises(ValueError, match="reviewed notes"):
        publisher.publish(receipt, directory, "Different notes", "Soota notes")
    assert all(c[0] == "api" for c in state["calls"])


def test_changed_asset_is_not_overwritten(release):
    receipt, directory, state = release
    publisher.publish(receipt, directory, "Product notes", "Soota notes")
    state["calls"].clear()
    key = next(k for k in state["releases"]["example/lorelab"]["bytes"] if k.endswith(".zip"))
    state["releases"]["example/lorelab"]["bytes"][key] = b"different asset"
    with pytest.raises(ValueError, match="published asset differs"):
        publisher.publish(receipt, directory, "Product notes", "Soota notes")
    assert not any(c[:2] == ["release", "upload"] for c in state["calls"])


def test_lookup_failure_does_not_create_release(release):
    receipt, directory, state = release
    state["lookup_error"] = True
    with pytest.raises(RuntimeError, match="lookup failed"):
        publisher.publish(receipt, directory, "Product notes", "Soota notes")
    assert not state["releases"]


def test_empty_notes_or_unexecuted_receipt_cannot_publish(release):
    receipt, directory, state = release
    with pytest.raises(ValueError, match="notes"):
        publisher.publish(receipt, directory, "", "Soota notes")
    receipt["executed"] = False
    with pytest.raises(ValueError, match="executed"):
        publisher.publish(receipt, directory, "Product notes", "Soota notes")
    assert not state["releases"]


def test_other_plugin_name_cannot_bypass_same_version_protection(release):
    receipt, directory, state = release
    publisher.publish(receipt, directory, "Product notes", "Soota notes")
    state["releases"]["example/lorelab"]["value"]["assets"].append({"name": "lorelab-plugin-1.0.0-other.zip"})
    state["calls"].clear()
    with pytest.raises(ValueError, match="different plugin"):
        publisher.publish(receipt, directory, "Product notes", "Soota notes")
    assert all(c[0] == "api" for c in state["calls"])


def test_candidate_plugin_must_match_committed_source_and_binding(release):
    receipt, directory, state = release
    plugin = next(directory.glob("*.zip"))
    with zipfile.ZipFile(plugin, "w") as archive:
        archive.writestr("lorelab/lorelab-binding.json", json.dumps({"version": "1.0.0",
            "source_fingerprint": "different-source", "components_lock_sha256": "c" * 64}))
    plugin.with_name(plugin.name + ".sha256").write_text(f"{publisher.digest(plugin)}  {plugin.name}\n")
    with pytest.raises(ValueError, match="plugin binding"):
        publisher.publish(receipt, directory, "Product notes", "Soota notes")
    assert not state["calls"]
