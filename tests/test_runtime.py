"""受管入口和用户配置的实际进程边界。"""
import hashlib
import json
import sys
import types

import pytest

from lorehub import cli
from lorelab import runtime


@pytest.fixture
def managed(tmp_path, monkeypatch):
    for prefix in ("LORELAB", "LOREHUB"):
        for suffix in ("ROOT", "RUNTIME_FILE"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    source = tmp_path / "source with spaces"
    source.mkdir()
    lock = source / "components.lock.json"
    lock.write_text('{"schema_version": 1}')
    script = source / "component.py"
    script.write_text('import json,sys; print(json.dumps({"args":sys.argv[1:]}))')
    manifest = tmp_path / "runtime.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "product": "lorehub",
        "components_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "tools": {"cubox": [sys.executable, str(script)]},
    }))
    monkeypatch.setenv("LOREHUB_ROOT", str(source))
    monkeypatch.setenv("LOREHUB_RUNTIME_FILE", str(manifest))
    return source, script


def test_exact_managed_executable_ignores_shadow_path(managed, tmp_path, monkeypatch):
    fake = tmp_path / "cubox-cli"
    fake.write_text('#!/bin/sh\nprintf "shadow executable"\nexit 99\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert runtime.run_json("cubox", ["card", "list"])["args"] == ["card", "list"]


def test_stale_lock_rejected_before_process(managed):
    source, _ = managed
    (source / "components.lock.json").write_text('{"changed": true}')
    with pytest.raises(runtime.ToolError, match="不一致"):
        runtime.run_json("cubox", [])


def test_partial_batch_receipt_is_private(managed, tmp_path):
    _, script = managed
    script.write_text('import sys; print("{\\"items\\": [], \\"status\\": \\"partial\\"}"); sys.exit(1)')
    receipt = tmp_path / "receipts" / "partial.json"
    value = runtime.run_json("cubox", [], receipt, (0, 1))
    assert value["status"] == "partial"
    assert json.loads(receipt.read_text()) == value
    assert receipt.stat().st_mode & 0o777 == 0o600


def test_invalid_json_does_not_echo_raw_output(managed):
    _, script = managed
    script.write_text('print("private-token-value")')
    with pytest.raises(runtime.ToolError) as error:
        runtime.run_json("cubox", [])
    assert "private-token-value" not in str(error.value)


def test_init_keeps_configuration_outside_source(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "configuration"))
    args = cli.parser().parse_args(["init", "--vault", str(vault), "--subdir", "Knowledge",
                                   "--mubu-doc", "example-document"])
    result = cli.dispatch(args)
    assert result["settings"]["delete_verified"] is False
    assert runtime.config_path().is_file()
    assert not list(vault.iterdir())
    args.subdir = "../outside"
    with pytest.raises(ValueError, match="子目录"):
        cli.dispatch(args)


def test_cli_tool_passes_arguments_without_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "forward", lambda name, args: calls.append((name, args)) or 0)
    assert cli.main(["tool", "cubox", "--", "card", "list", "--keyword", "a; echo b"]) == 0
    assert calls == [("cubox", ["card", "list", "--keyword", "a; echo b"])]


def test_old_import_shares_canonical_module_and_version(monkeypatch):
    import lorehub
    import lorehub.runtime as legacy
    import lorelab

    assert legacy is runtime
    assert lorehub.__version__ == lorelab.__version__ == "0.1.0"
    monkeypatch.setattr(legacy, "tool_command", lambda _: ["bound"])
    assert runtime.tool_command("cubox") == ["bound"]


@pytest.mark.parametrize("namespace", ["LORELAB", "both"])
def test_new_and_equal_dual_bindings_use_same_runtime(managed, monkeypatch, namespace):
    source, _ = managed
    monkeypatch.setenv("LORELAB_ROOT", str(source))
    monkeypatch.setenv("LORELAB_RUNTIME_FILE", str(source.parent / "runtime.json"))
    if namespace == "LORELAB":
        monkeypatch.delenv("LOREHUB_ROOT")
        monkeypatch.delenv("LOREHUB_RUNTIME_FILE")
    assert runtime.root() == source
    assert runtime.run_json("cubox", ["list"])["args"] == ["list"]


@pytest.mark.parametrize("new_root,new_runtime", [(True, False), (False, True), (True, True)])
def test_conflicting_or_cross_namespace_binding_never_runs(managed, monkeypatch, new_root, new_runtime):
    source, _ = managed
    if new_root:
        monkeypatch.setenv("LORELAB_ROOT", str(source if not new_runtime else source / "other"))
    if new_runtime:
        monkeypatch.setenv("LORELAB_RUNTIME_FILE", str(source.parent / "runtime.json"))
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **k: pytest.fail("mixed runtime invoked"))
    with pytest.raises(runtime.ToolError, match="冲突"):
        runtime.run_json("cubox", [])


@pytest.mark.parametrize("field", ["source_root", "components_lock"])
def test_source_path_binding_rejects_same_lock_in_other_install(managed, field):
    source, _ = managed
    path = source.parent / "runtime.json"
    value = json.loads(path.read_text())
    value.update(product="lorelab", source_root=str(source), components_lock=str(source / "components.lock.json"))
    path.write_text(json.dumps(value))
    assert runtime.runtime_manifest() == value
    value[field] = str(source.parent / "other-install")
    path.write_text(json.dumps(value))
    with pytest.raises(runtime.ToolError, match="源码路径"):
        runtime.runtime_manifest()


def test_new_manifest_rejects_wrong_product_and_invalid_json(managed):
    source, _ = managed
    path = source.parent / "runtime.json"
    value = json.loads(path.read_text())
    value["product"] = "other"
    path.write_text(json.dumps(value))
    with pytest.raises(runtime.ToolError, match="不一致"):
        runtime.runtime_manifest()
    path.write_text("invalid")
    with pytest.raises(runtime.ToolError, match="无法读取"):
        runtime.runtime_manifest()


def test_config_methods_delegate_to_soota_without_own_storage(monkeypatch, tmp_path):
    knowledge_runtime = types.ModuleType("soota.knowledge.runtime")
    path = tmp_path / "chosen-by-soota.json"
    settings = {"preserved": True}
    calls = []
    knowledge_runtime.config_path = lambda: calls.append("path") or path
    knowledge_runtime.read_config = lambda: calls.append("read") or settings
    monkeypatch.setitem(sys.modules, "soota.knowledge.runtime", knowledge_runtime)
    assert runtime.config_path() == path
    assert runtime.read_config() is settings
    assert calls == ["path", "read"]
    assert not path.exists()


def test_missing_managed_executable_does_not_fall_back(managed):
    source, _ = managed
    path = source.parent / "runtime.json"
    value = json.loads(path.read_text())
    value["tools"]["cubox"] = [str(source / "absent-executable")]
    path.write_text(json.dumps(value))
    with pytest.raises(runtime.ToolError, match="不会退回 PATH"):
        runtime.run_json("cubox", [])


def test_component_process_receives_same_explicit_soota_binding(managed, monkeypatch):
    source, script = managed
    script.write_text("import json,os; print(json.dumps({k:v for k,v in os.environ.items() "
                      "if k.startswith(('LORELAB_', 'LOREHUB_', 'SOOTA_KNOWLEDGE_'))}))")
    monkeypatch.setenv("SOOTA_KNOWLEDGE_RUNTIME_FILE", "/wrong/runtime.json")
    monkeypatch.setenv("SOOTA_KNOWLEDGE_COMPONENTS_LOCK", "/wrong/components.lock.json")
    env = runtime.run_json("cubox", [])
    assert env["LORELAB_ROOT"] == env["LOREHUB_ROOT"] == str(source)
    assert env["SOOTA_KNOWLEDGE_RUNTIME_FILE"] == env["LORELAB_RUNTIME_FILE"] == env["LOREHUB_RUNTIME_FILE"]
    assert env["SOOTA_KNOWLEDGE_COMPONENTS_LOCK"] == str(source / "components.lock.json")
