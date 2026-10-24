"""统一版本准备的元数据边界、幂等性及失败恢复。"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

from lorelab import components, release_versions

REPOSITORY = Path(__file__).resolve().parents[1]
INITIAL = {"lorelab": "0.1.0", "soota": "0.1.0"}
TARGET = {"lorelab": "0.2.0", "soota": "0.3.1"}
PROJECTS = {"pyproject.toml": "lorelab", "modules/soota/pyproject.toml": "soota"}
INITS = {"src/lorelab/__init__.py": "lorelab", "modules/soota/src/soota/__init__.py": "soota"}
LOCKS = {"uv.lock": {"lorelab", "soota"}, "modules/soota/uv.lock": {"soota"}}
METADATA = {*PROJECTS, *INITS, *LOCKS, "components.lock.json"}


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def write_json(root: Path, lock: dict) -> None:
    (root / "components.lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def manifest(root: Path) -> dict:
    return json.loads((root / "components.lock.json").read_bytes())


def change(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "product"
    files = {
        "pyproject.toml": """[project]
name = "lorelab"
version = "0.1.0" # product version
dependencies = ["soota>=0.1.0", "dependency==4.5.6"]

[tool.release]
version = "0.1.0" # unrelated metadata
""",
        "modules/soota/pyproject.toml": """[project]
name = "soota"
version = "0.1.0"
dependencies = ["dependency==4.5.6"]
""",
        "modules/soota/src/soota/source.py": "VALUE = 1\n",
        "modules/soota/skills/soota/SKILL.md": "---\nname: soota\n---\nSynthetic skill.\n",
        "modules/demo/source.py": "VALUE = 2\n",
        "modules/demo/skills/demo/SKILL.md": "---\nname: demo\n---\nSynthetic skill.\n",
        "user-notes.md": "Keep this unrelated working file.\n",
    }
    dependency = """[[package]]
name = "dependency"
version = "4.5.6"
source = { registry = "https://example.invalid/simple" }
wheels = [{ url = "https://example.invalid/dependency.whl", hash = "sha256:abc", size = 123 }]

"""
    header = 'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n\n'
    lorelab = """[[package]]
name = "lorelab"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "soota" }, { name = "dependency", version = "4.5.6" }]

[package.metadata]
requires-dist = [{ name = "soota", directory = "modules/soota" }]

"""
    soota = """[[package]]
name = "soota"
version = "0.1.0" # local package only
source = { editable = "." }
dependencies = [{ name = "dependency", version = "4.5.6" }]

[package.metadata]
requires-dist = [{ name = "dependency", specifier = "==4.5.6" }]
"""
    files["uv.lock"] = header + dependency + lorelab + soota.replace('editable = "."', 'directory = "modules/soota"')
    files["modules/soota/uv.lock"] = header + dependency + soota
    # 使用仓库实际入口的布局；版本值固定为合成数据，不导入待测项目的入口模块。
    for relative in INITS:
        text = (REPOSITORY / relative).read_text(encoding="utf-8")
        text, count = re.subn(r"""(?m)^(__version__\s*=\s*["'])[^"']+(["'])""", r"\g<1>0.1.0\2", text)
        assert count == 1
        files[relative] = text
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    write_json(
        root,
        {
            "schema_version": 1,
            "product": {"name": "lorelab", "version": "0.1.0", "extra": "preserve"},
            "components": {
                "soota": {
                    "path": "modules/soota",
                    "repository": "https://example.invalid/soota.git",
                    "revision": "d0f20bc" + "0" * 33,
                    "version": "0.1.0+d0f20bc",
                    "skill": {"name": "soota", "path": "modules/soota/skills/soota"},
                    "extension": {"keep": True},
                },
                "demo": {
                    "path": "modules/demo",
                    "repository": "https://example.invalid/demo.git",
                    "revision": "b" * 40,
                    "version": "1.0.0+import",
                    "skill": {"name": "demo", "path": "modules/demo/skills/demo"},
                },
            },
            "extension": {"keep": True},
        },
    )
    assert components.refresh(root)["ok"]
    return root


def test_versions_accepts_legacy_without_writing_or_importing_init(root: Path):
    with (root / "src/lorelab/__init__.py").open("a") as stream:
        stream.write('\nraise RuntimeError("must not execute local init")\n')
    before = snapshot(root)
    assert release_versions.versions(root) == INITIAL
    assert snapshot(root) == before


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    [
        ("pyproject.toml", 'version = "0.1.0"', 'version = "0.2.0"'),
        ("modules/soota/pyproject.toml", 'version = "0.1.0"', 'version = "0.2.0"'),
        *[(relative, '__version__ = "0.1.0"', '__version__ = "0.2.0"') for relative in INITS],
        ("uv.lock", 'name = "lorelab"\nversion = "0.1.0"', 'name = "lorelab"\nversion = "0.2.0"'),
        ("uv.lock", 'name = "soota"\nversion = "0.1.0"', 'name = "soota"\nversion = "0.2.0"'),
        ("modules/soota/uv.lock", 'name = "soota"\nversion = "0.1.0"', 'name = "soota"\nversion = "0.2.0"'),
        ("components.lock.json", '"version": "0.1.0"', '"version": "0.2.0"'),
        ("components.lock.json", '"version": "0.1.0+d0f20bc"', '"version": "0.2.0"'),
    ],
)
def test_local_version_mismatch_is_rejected_before_writing(root: Path, relative: str, old: str, new: str, monkeypatch):
    change(root, relative, old, new)
    before = snapshot(root)
    monkeypatch.setattr(release_versions, "_write", lambda *args: pytest.fail("must validate before writing"))
    for operation in (
        lambda: release_versions.versions(root),
        lambda: release_versions.prepare(root, "0.3.0", "0.3.0"),
    ):
        with pytest.raises(ValueError, match="version mismatch"):
            operation()
    assert snapshot(root) == before


def test_prepare_synchronizes_only_seven_metadata_files_and_keeps_dependencies(root: Path, monkeypatch):
    before = snapshot(root)
    old_lock = manifest(root)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run a resolver"))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not spawn a resolver"))
    report = release_versions.prepare(root, product_version=TARGET["lorelab"], soota_version=TARGET["soota"])
    after = snapshot(root)
    assert report["ok"] and report["components"]["ok"]
    assert report["before"] == INITIAL and report["after"] == TARGET
    assert set(report["changed_paths"]) == {path for path in before if before[path] != after[path]} == METADATA
    assert set(before) == set(after)
    assert release_versions.versions(root) == TARGET
    for relative, name in PROJECTS.items():
        expected = tomllib.loads(before[relative].decode())
        expected["project"]["version"] = TARGET[name]
        assert tomllib.loads(after[relative].decode()) == expected
        assert after[relative] == before[relative].replace(
            b'version = "0.1.0"', f'version = "{TARGET[name]}"'.encode(), 1
        )
    for relative, names in LOCKS.items():
        expected = tomllib.loads(before[relative].decode())
        expected_bytes = before[relative]
        for package in expected["package"]:
            if package["name"] in names:
                package["version"] = TARGET[package["name"]]
        for name in names:
            expected_bytes = expected_bytes.replace(
                f'name = "{name}"\nversion = "0.1.0"'.encode(),
                f'name = "{name}"\nversion = "{TARGET[name]}"'.encode(),
            )
        assert tomllib.loads(after[relative].decode()) == expected
        assert after[relative] == expected_bytes
    for relative, name in INITS.items():
        assert after[relative] == before[relative].replace(
            b'__version__ = "0.1.0"', f'__version__ = "{TARGET[name]}"'.encode()
        )
    updated = manifest(root)
    assert updated["components"]["soota"]["import_version"] == "0.1.0+d0f20bc"
    expected = copy.deepcopy(old_lock)
    expected["product"]["version"] = TARGET["lorelab"]
    expected["components"]["soota"].update(
        {
            "version": TARGET["soota"],
            "import_version": "0.1.0+d0f20bc",
            "tree_sha256": updated["components"]["soota"]["tree_sha256"],
        }
    )
    assert updated == expected
    assert components.verify(root)["ok"]


def test_legacy_conversion_at_same_version_preserves_existing_import_version(root: Path):
    lock = manifest(root)
    lock["components"]["soota"]["import_version"] = "recorded-import"
    write_json(root, lock)
    report = release_versions.prepare(root, "0.1.0", "0.1.0")
    updated = manifest(root)["components"]["soota"]
    assert updated["version"] == "0.1.0"
    assert updated["import_version"] == "recorded-import"
    assert report["changed_paths"] == ["components.lock.json"]


@pytest.mark.parametrize(
    "relative",
    [
        "modules/soota/src/soota/source.py",
        "modules/soota/skills/soota/SKILL.md",
        "modules/demo/source.py",
        "modules/demo/skills/demo/SKILL.md",
    ],
)
def test_source_or_skill_only_changes_refresh_without_bumping_versions(root: Path, relative: str):
    release_versions.prepare(root, "0.1.0", "0.1.0")
    path = root / relative
    path.write_bytes(path.read_bytes() + b"\n# edited during normal development\n")
    assert not components.verify(root)["ok"]
    before = snapshot(root)
    old_lock = manifest(root)
    assert release_versions.versions(root) == INITIAL
    report = release_versions.prepare(root, "0.1.0", "0.1.0")
    assert report["changed_paths"] == ["components.lock.json"]
    assert report["before"] == report["after"] == INITIAL
    after = snapshot(root)
    assert {key: value for key, value in before.items() if key != "components.lock.json"} == {
        key: value for key, value in after.items() if key != "components.lock.json"
    }
    for name, entry in manifest(root)["components"].items():
        assert entry["revision"] == old_lock["components"][name]["revision"]
    assert components.verify(root)["ok"]


def test_repeated_prepare_changes_no_bytes_and_preserves_modes(root: Path):
    for relative in METADATA:
        (root / relative).chmod(0o640)
    release_versions.prepare(root, "0.2.0", "0.3.1")
    before = snapshot(root)
    report = release_versions.prepare(root, "0.2.0", "0.3.1")
    assert report["changed_paths"] == []
    assert report["before"] == report["after"] == TARGET
    assert snapshot(root) == before
    assert all(stat.S_IMODE((root / path).stat().st_mode) == 0o640 for path in METADATA)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "0.2",
        "v0.2.0",
        "0.2.0rc1",
        "0.2.0+local",
        " 0.2.0",
        "0.2.0\n",
        "01.2.0",
        "0.02.0",
        "0.2.00",
        "-1.2.0",
        "０.2.0",
        None,
        2,
        True,
    ],
)
def test_invalid_target_is_rejected_before_writing(root: Path, invalid, index: int, monkeypatch):
    before = snapshot(root)
    targets = ["0.2.0", "0.3.1"]
    targets[index] = invalid
    monkeypatch.setattr(release_versions, "_write", lambda *args: pytest.fail("must validate before writing"))
    with pytest.raises(ValueError, match="strict X.Y.Z"):
        release_versions.prepare(root, *targets)
    assert snapshot(root) == before


@pytest.mark.parametrize(("product", "soota"), [("0.0.9", "0.3.1"), ("0.2.0", "0.0.9")])
def test_downgrade_of_either_package_is_rejected(root: Path, product: str, soota: str):
    before = snapshot(root)
    with pytest.raises(ValueError, match="downgrade"):
        release_versions.prepare(root, product, soota)
    assert snapshot(root) == before


def test_versions_compare_numerically_and_can_advance_independently(root: Path):
    release_versions.prepare(root, "0.9.0", "0.1.0")
    release_versions.prepare(root, "0.10.0", "0.1.0")
    assert release_versions.versions(root) == {"lorelab": "0.10.0", "soota": "0.1.0"}
    with pytest.raises(ValueError, match="downgrade"):
        release_versions.prepare(root, "0.9.9", "0.1.0")


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    [
        ("pyproject.toml", 'name = "lorelab"', 'name = "other"'),
        ("modules/soota/pyproject.toml", 'name = "soota"', 'name = "other"'),
        ("pyproject.toml", "[project]", '[project]\ndynamic = ["version"]'),
        ("pyproject.toml", 'version = "0.1.0"', "version = 1"),
        ("src/lorelab/__init__.py", '__version__ = "0.1.0"', '__version__ = str("0.1.0")'),
        ("src/lorelab/__init__.py", '__version__ = "0.1.0"', '__version__ = "0.1.0"\n__version__ = "0.1.0"'),
        ("uv.lock", "version = 1", "version = 2"),
        ("uv.lock", "revision = 3", "revision = true"),
        ("uv.lock", 'name = "lorelab"', 'name = "other"'),
        ("modules/soota/uv.lock", 'name = "soota"', 'name = "other"'),
        (
            "uv.lock",
            'source = { directory = "modules/soota" }',
            'source = { registry = "https://example.invalid/simple" }',
        ),
        ("modules/soota/uv.lock", 'editable = "."', 'editable = "../soota"'),
        ("uv.lock", 'name = "dependency"', 'label = "dependency"'),
        ("components.lock.json", '"schema_version": 1', '"schema_version": true'),
        ("components.lock.json", '"name": "lorelab"', '"name": "other"'),
        ("components.lock.json", '"path": "modules/soota"', '"path": "modules/demo"'),
        ("components.lock.json", '"version": "0.1.0+d0f20bc"', '"version": "0.1.0+unknown"'),
        ("components.lock.json", '"path": "modules/demo"', '"path": "../outside"'),
    ],
)
def test_invalid_metadata_is_rejected_before_writing(root: Path, relative: str, old: str, new: str, monkeypatch):
    change(root, relative, old, new)
    before = snapshot(root)
    monkeypatch.setattr(release_versions, "_write", lambda *args: pytest.fail("must validate before writing"))
    with pytest.raises(ValueError):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert snapshot(root) == before


@pytest.mark.parametrize("relative", sorted(METADATA))
def test_missing_metadata_never_partially_writes(root: Path, relative: str):
    (root / relative).unlink()
    before = snapshot(root)
    with pytest.raises(ValueError, match="metadata file"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert snapshot(root) == before


def test_missing_skill_is_rejected_before_writing(root: Path, monkeypatch):
    (root / "modules/demo/skills/demo/SKILL.md").unlink()
    before = snapshot(root)
    monkeypatch.setattr(release_versions, "_write", lambda *args: pytest.fail("must validate before writing"))
    with pytest.raises(ValueError, match="Skill entrypoint"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert snapshot(root) == before


@pytest.mark.parametrize("relative", ["pyproject.toml", "modules/soota/src/soota/__init__.py", "components.lock.json"])
def test_symlink_metadata_cannot_write_outside_root(root: Path, tmp_path: Path, relative: str):
    path = root / relative
    outside = tmp_path / "external"
    path.rename(outside)
    original = outside.read_bytes()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic links"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert outside.read_bytes() == original
    assert path.is_symlink()


@pytest.mark.parametrize("failed_path", sorted(METADATA))
def test_write_failure_rolls_back_every_metadata_byte_and_mode(root: Path, failed_path: str, monkeypatch):
    for relative in METADATA:
        (root / relative).chmod(0o640)
    before = snapshot(root)
    replace = os.replace

    def failing_replace(source, destination):
        if Path(destination) == root / failed_path:
            raise OSError("simulated write failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert snapshot(root) == before
    assert all(stat.S_IMODE((root / path).stat().st_mode) == 0o640 for path in METADATA)


def test_refresh_atomic_write_failure_restores_all_seven_files(root: Path, monkeypatch):
    before = snapshot(root)
    replace = os.replace
    lock_writes = 0

    def failing_replace(source, destination):
        nonlocal lock_writes
        if Path(destination) == root / "components.lock.json":
            lock_writes += 1
            if lock_writes == 2:
                raise OSError("refresh lock write failed")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(RuntimeError, match="refresh lock write failed"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert lock_writes == 3  # 版本元数据写入、指纹刷新失败、回滚恢复。
    assert snapshot(root) == before


def test_failure_after_a_metadata_write_also_restores_that_file(root: Path, monkeypatch):
    before = snapshot(root)
    write = release_versions._write
    failed = False

    def failing_write(path, content, mode):
        nonlocal failed
        write(path, content, mode)
        if path == root / "modules/soota/uv.lock" and not failed:
            failed = True
            raise OSError("failure after replacing metadata")

    monkeypatch.setattr(release_versions, "_write", failing_write)
    with pytest.raises(RuntimeError, match="failure after replacing metadata"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert failed
    assert snapshot(root) == before


def test_failure_after_refresh_restores_metadata_but_keeps_unrelated_work(root: Path, monkeypatch):
    before = snapshot(root)
    refresh = components.refresh

    def failing_refresh(path):
        assert refresh(path)["ok"]
        (root / "user-notes.md").write_text("Changed independently during preparation.\n")
        (root / "modules/soota/src/soota/source.py").write_text("VALUE = 99\n")
        return {"ok": False, "errors": ["failure after refresh"]}

    monkeypatch.setattr(components, "refresh", failing_refresh)
    with pytest.raises(RuntimeError, match="failure after refresh"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    after = snapshot(root)
    assert {path: after[path] for path in METADATA} == {path: before[path] for path in METADATA}
    assert (root / "user-notes.md").read_text() == "Changed independently during preparation.\n"
    assert (root / "modules/soota/src/soota/source.py").read_text() == "VALUE = 99\n"
    assert set(after) == set(before)


def test_final_verify_failure_rolls_back(root: Path, monkeypatch):
    before = snapshot(root)
    verify = components.verify
    calls = 0

    def failing_verify(path):
        nonlocal calls
        calls += 1
        return verify(path) if calls == 1 else {"ok": False, "errors": ["final verify failed"]}

    monkeypatch.setattr(components, "verify", failing_verify)
    with pytest.raises(RuntimeError, match="final verify failed"):
        release_versions.prepare(root, "0.2.0", "0.3.1")
    assert calls == 2
    assert snapshot(root) == before


def test_crlf_quotes_and_unicode_are_preserved(root: Path):
    for relative in (*PROJECTS, *INITS, *LOCKS):
        path = root / relative
        text = path.read_text(encoding="utf-8").replace('"0.1.0"', "'0.1.0'")
        if relative in INITS:
            text = "# 中文注释\n" + text.replace("__version__ =", 'label = "中文"; __version__ =')
        path.write_bytes(text.replace("\n", "\r\n").encode())
    before = snapshot(root)
    release_versions.prepare(root, "0.2.0", "0.3.1")
    for relative, name in INITS.items():
        data = (root / relative).read_bytes()
        assert data == before[relative].replace(b"'0.1.0'", f"'{TARGET[name]}'".encode(), 1)
        tree = ast.parse(data)
        value = next(
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__version__"
        )
        assert value == TARGET[name]
    assert release_versions.versions(root) == TARGET
