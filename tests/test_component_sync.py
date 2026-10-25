"""真实 Git 仓库验证单向同步、历史保留、分歧保护与重跑。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lorelab.component_sync import git, synchronize
from lorelab.components import PROVENANCE_FILE, refresh


def commit(root, message="test change"):
    git(root, "add", "--all")
    git(root, "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def fixture_repositories(base: Path):
    original = base / "original"
    original.mkdir()
    git(original, "init", "-q", "-b", "main")
    files = {"pyproject.toml": '[project]\nname = "soota"\nversion = "1.0.0"\n',
             "src/soota/__init__.py": '__version__ = "1.0.0"\n',
             "uv.lock": 'version = 1\n[[package]]\nname = "soota"\nversion = "1.0.0"\n'
                        'source = { editable = "." }\n',
             "skills/soota/SKILL.md": "---\nname: soota\ndescription: Synthetic test skill\n---\nRead context.\n",
             "工具.txt": "Original text\n"}
    for name, data in files.items():
        path = original / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
    baseline = commit(original, "original history")
    target = base / "standalone.git"
    git(base, "clone", "--quiet", "--bare", str(original), str(target))
    source = base / "product"
    component = source / "modules/soota"
    shutil.copytree(original, component, ignore=shutil.ignore_patterns(".git"))
    (source / "pyproject.toml").write_text('[project]\nname = "lorelab"\nversion = "1.0.0"\n')
    (source / "src/lorelab").mkdir(parents=True)
    (source / "src/lorelab/__init__.py").write_text('__version__ = "1.0.0"\n')
    (source / "uv.lock").write_text('version = 1\n[[package]]\nname = "lorelab"\nversion = "1.0.0"\n'
                                   'source = { editable = "." }\n[[package]]\nname = "soota"\n'
                                   'version = "1.0.0"\nsource = { directory = "modules/soota" }\n')
    lock = {"schema_version": 1, "product": {"name": "lorelab", "version": "1.0.0"},
            "components": {"soota": {"path": "modules/soota", "repository": str(target),
                         "revision": baseline, "version": "1.0.0",
                         "skill": {"name": "soota", "path": "modules/soota/skills/soota"}}}}
    (source / "components.lock.json").write_text(json.dumps(lock))
    assert refresh(source)["ok"]
    git(source, "init", "-q", "-b", "main")
    commit(source, "import component")
    return source, target, original, baseline


@pytest.fixture
def repos(tmp_path):
    return fixture_repositories(tmp_path)


def change(source, name="工具.txt", text="Source changed\n"):
    (source / "modules/soota" / name).write_text(text, encoding="utf-8")
    assert refresh(source)["ok"]
    return commit(source)


def test_preview_then_sync_preserves_original_history_and_skill(repos, tmp_path):
    source, target, original, baseline = repos
    head = change(source)
    before = (original / "工具.txt").read_bytes()
    preview = synchronize(source)
    assert preview["source_commit"] == head and not preview["executed"]
    assert git(target, "rev-parse", "main") == baseline
    result = synchronize(source, execute=True)
    assert result["commit"] == preview["commit"]
    assert git(target, "rev-parse", "main^") == baseline
    assert git(target, "show", "main:工具.txt") == "Source changed"
    assert git(target, "show", "main:skills/soota/SKILL.md") == (source / "modules/soota/skills/soota/SKILL.md").read_text().rstrip()
    assert (original / "工具.txt").read_bytes() == before
    assert not git(original, "status", "--porcelain")
    second = synchronize(source, execute=True)
    assert not second["changed"] and second["commit"] == result["commit"]


def test_source_and_skill_change_are_delivered_together(repos):
    source, target, _, _ = repos
    first = synchronize(source, execute=True)
    change(source, "skills/soota/SKILL.md", "---\nname: soota\ndescription: Updated synthetic skill\n---\n")
    (source / "modules/soota/工具.txt").unlink()
    assert refresh(source)["ok"]
    commit(source)
    second = synchronize(source, execute=True)
    assert git(target, "rev-parse", "main^") == first["commit"]
    assert "工具.txt" not in git(target, "ls-tree", "-r", "--name-only", "main").splitlines()
    receipt = json.loads(git(target, "show", "main:" + PROVENANCE_FILE))
    assert receipt["sync"]["source_commit"] == second["source_commit"]
    assert second["tree_sha256"] != first["tree_sha256"]


def test_unchanged_component_does_not_create_extra_sync_commit(repos):
    source, _, _, _ = repos
    first = synchronize(source, execute=True)
    (source / "product-doc.md").write_text("Product documentation")
    commit(source)
    result = synchronize(source, execute=True)
    assert not result["changed"] and result["commit"] == first["commit"]


def test_dirty_or_unlocked_source_never_updates_target(repos):
    source, target, _, baseline = repos
    (source / "modules/soota/工具.txt").write_text("unreviewed")
    with pytest.raises(ValueError, match="commit"):
        synchronize(source, execute=True)
    commit(source)
    with pytest.raises(ValueError, match="fingerprint"):
        synchronize(source, execute=True)
    assert git(target, "rev-parse", "main") == baseline


def test_unexpected_standalone_commit_is_preserved(repos, tmp_path):
    source, target, _, _ = repos
    synchronize(source, execute=True)
    other = tmp_path / "other"
    git(tmp_path, "clone", "--quiet", str(target), str(other))
    (other / "工具.txt").write_text("Do not lose this independent edit")
    external = commit(other)
    git(other, "push", "--quiet", "origin", "main")
    change(source)
    with pytest.raises(ValueError, match="outside LoreLab"):
        synchronize(source, execute=True)
    assert git(target, "rev-parse", "main") == external


def test_stale_source_job_cannot_rollback_newer_sync(repos, tmp_path):
    source, target, _, _ = repos
    synchronize(source, execute=True)
    old = tmp_path / "old-source"
    git(tmp_path, "clone", "--quiet", str(source), str(old))
    change(source)
    current = synchronize(source, execute=True)
    with pytest.raises(RuntimeError):
        synchronize(old, execute=True)
    assert git(target, "rev-parse", "main") == current["commit"]


def test_original_unpushed_commits_survive_bootstrap(repos):
    source, target, original, remote_base = repos
    (original / "previous.txt").write_text("An original unpushed commit")
    local_base = commit(original, "unpublished original work")
    lock_path = source / "components.lock.json"
    lock = json.loads(lock_path.read_text())
    lock["components"]["soota"]["revision"] = local_base
    lock_path.write_text(json.dumps(lock))
    (source / "modules/soota/previous.txt").write_text("An original unpushed commit")
    assert refresh(source)["ok"]
    commit(source)
    git(source, "fetch", "--quiet", str(original), "main")
    git(source, "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
        "merge", "--quiet", "--strategy=ours", "--allow-unrelated-histories", "--no-ff", "-m", "retain history", "FETCH_HEAD")
    result = synchronize(source, execute=True)
    assert git(target, "rev-parse", "main^") == local_base
    git(target, "merge-base", "--is-ancestor", remote_base, result["commit"])
    assert git(target, "show", "main:previous.txt") == "An original unpushed commit"


def test_bootstrap_rejects_diverged_original_branch(repos):
    source, target, original, _ = repos
    (original / "external.txt").write_text("new independent change")
    other = commit(original)
    git(original, "push", "--quiet", str(target), "main")
    with pytest.raises(RuntimeError):
        synchronize(source, execute=True)
    assert git(target, "rev-parse", "main") == other


def test_non_fast_forward_race_is_rejected(repos, monkeypatch):
    source, target, original, _ = repos
    from lorelab import component_sync

    real = component_sync.git
    raced = False

    def racing(root, *args, **kwargs):
        nonlocal raced
        if args[0] == "push" and not raced:
            raced = True
            (original / "race.txt").write_text("Concurrent work")
            commit(original)
            real(original, "push", "--quiet", str(target), "main")
        return real(root, *args, **kwargs)

    monkeypatch.setattr(component_sync, "git", racing)
    with pytest.raises(RuntimeError, match="push failed"):
        synchronize(source, execute=True)
    assert git(target, "show", "main:race.txt") == "Concurrent work"


def test_no_source_history_is_injected_into_independent_repo(repos):
    source, target, _, _ = repos
    synchronize(source, execute=True)
    source_head = git(source, "rev-parse", "HEAD")
    result = subprocess.run(["git", "-C", str(target), "cat-file", "-e", source_head],
                            capture_output=True, check=False)
    assert result.returncode != 0


@pytest.fixture(params=["cubox", "mubu"])
def named_repos(tmp_path, request):
    source, target, original, baseline = fixture_repositories(tmp_path)
    name = request.param
    relative = f"modules/{name}-cli"
    component = source / relative
    (source / "modules/soota").rename(component)
    skill = "skills/cubox/SKILL.md" if name == "cubox" else "SKILL.md"
    (component / skill).parent.mkdir(parents=True, exist_ok=True)
    (component / "skills/soota/SKILL.md").rename(component / skill)
    skill_name = "cubox" if name == "cubox" else "mubu-integration"
    (component / skill).write_text(f"---\nname: {skill_name}\ndescription: Synthetic skill\n---\nRead context.\n")
    lock_path = source / "components.lock.json"
    lock = json.loads(lock_path.read_text())
    entry = lock["components"].pop("soota")
    entry.update(path=relative, skill={"name": skill_name, "path": str(Path(relative) / Path(skill).parent)})
    lock["components"][name] = entry
    lock_path.write_text(json.dumps(lock))
    assert refresh(source)["ok"]
    commit(source)
    return source, target, original, baseline, name, component, skill


def test_named_component_cli_delivers_source_and_skill_with_history(named_repos, capsys):
    from lorelab.cli import main

    source, target, original, baseline, name, component, skill = named_repos
    assert main(["components", "sync", name, "--source", str(source)]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["component"] == name and not preview["executed"]
    assert git(target, "rev-parse", "main") == baseline
    assert main(["components", "sync", name, "--source", str(source), "--execute"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["executed"] and result["commit"] == preview["commit"]
    assert git(target, "rev-parse", "main^") == baseline
    receipt = json.loads(git(target, "show", "main:" + PROVENANCE_FILE))
    assert receipt["component"] == name
    assert receipt["skill"]["path"] == str(Path(skill).parent)
    assert git(target, "show", "main:" + skill) == (component / skill).read_text().rstrip()
    assert not git(original, "status", "--porcelain")
    (component / "工具.txt").unlink()
    (component / skill).write_text((component / skill).read_text() + "Updated reference.\n")
    assert refresh(source)["ok"]
    commit(source)
    changed = synchronize(source, name=name, execute=True)
    assert changed["changed"]
    assert git(target, "rev-parse", "main^") == result["commit"]
    assert "工具.txt" not in git(target, "ls-tree", "-r", "--name-only", "main").splitlines()
    assert not synchronize(source, name=name, execute=True)["changed"]


def test_named_component_rejects_independent_changes(named_repos):
    source, target, original, _, name, _, _ = named_repos
    synchronize(source, name=name, execute=True)
    git(original, "fetch", str(target), "main")
    git(original, "merge", "--ff-only", "FETCH_HEAD")
    (original / "independent.txt").write_text("Preserve independent work")
    external = commit(original)
    git(original, "push", str(target), "main")
    with pytest.raises(ValueError, match="outside LoreLab"):
        synchronize(source, name=name, execute=True)
    assert git(target, "rev-parse", "main") == external


def test_receipt_for_another_component_cannot_be_overwritten(named_repos):
    source, target, _, _, name, _, _ = named_repos
    current = synchronize(source, name=name, execute=True)
    lock_path = source / "components.lock.json"
    lock = json.loads(lock_path.read_text())
    # Even identical files and a valid lock do not authorize a differently named component.
    lock["components"]["soota"] = dict(lock["components"][name])
    lock_path.write_text(json.dumps(lock))
    commit(source)
    with pytest.raises(ValueError, match="not managed"):
        synchronize(source, target=str(target), execute=True)
    assert git(target, "rev-parse", "main") == current["commit"]
