"""配对版本发布的真实 Git 标签、拒绝覆盖及中断恢复。"""

import os

import pytest
from test_component_sync import change, commit, fixture_repositories

from lorelab.component_sync import git, synchronize
from lorelab.releases import publish


@pytest.fixture
def repos(tmp_path):
    source, soota, original, baseline = fixture_repositories(tmp_path)
    product = tmp_path / "lorelab.git"
    git(tmp_path, "clone", "--quiet", "--bare", str(source), str(product))
    return source, soota, product, original, baseline


def test_paired_tags_are_previewed_then_published_and_repeated(repos):
    source, soota, product, _, _ = repos
    report = publish(source, product_repository=str(product))
    assert not report["executed"]
    assert not git(soota, "tag") and not git(product, "tag")
    result = publish(source, product_repository=str(product), execute=True)
    assert git(soota, "rev-parse", "v1.0.0") == result["soota"]["commit"]
    assert git(product, "rev-parse", "v1.0.0") == result["lorelab"]["commit"]
    repeated = publish(source, product_repository=str(product), execute=True)
    assert repeated["soota"]["commit"] == result["soota"]["commit"]
    assert not repeated["soota"]["changed"]


def test_existing_conflicting_product_tag_stops_before_soota_sync(repos):
    source, soota, product, _, baseline = repos
    git(product, "tag", "v1.0.0", "main")
    change(source)
    git(source, "push", "--quiet", str(product), "main")
    with pytest.raises(ValueError, match="different LoreLab"):
        publish(source, product_repository=str(product), execute=True)
    assert git(soota, "rev-parse", "main") == baseline
    assert not git(soota, "tag")


def test_conflicting_soota_tag_preserves_both_repositories(repos):
    source, soota, product, _, baseline = repos
    git(soota, "tag", "v1.0.0", baseline)
    with pytest.raises(ValueError, match="different standalone"):
        publish(source, product_repository=str(product), execute=True)
    assert git(soota, "rev-parse", "main") == baseline
    assert not git(product, "tag")


def test_product_branch_must_contain_exact_reviewed_source(repos):
    source, soota, product, _, baseline = repos
    change(source)
    with pytest.raises(ValueError, match="source commit"):
        publish(source, product_repository=str(product), execute=True)
    assert git(soota, "rev-parse", "main") == baseline


@pytest.mark.skipif(os.name == "nt", reason="POSIX Git test hook")
def test_partial_release_resumes_without_rewriting_soota(repos):
    source, soota, product, _, _ = repos
    hook = product / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(RuntimeError, match="push failed"):
        publish(source, product_repository=str(product), execute=True)
    existing = git(soota, "rev-parse", "v1.0.0")
    assert not git(product, "tag")
    hook.unlink()
    resumed = publish(source, product_repository=str(product), execute=True)
    assert resumed["soota"]["commit"] == existing and not resumed["soota"]["changed"]
    assert git(product, "rev-parse", "v1.0.0") == git(source, "rev-parse", "HEAD")


def test_previously_synchronized_component_gets_tag_without_extra_commit(repos):
    source, soota, product, _, _ = repos
    synced = synchronize(source, execute=True)
    released = publish(source, product_repository=str(product), execute=True)
    assert not released["soota"]["changed"]
    assert git(soota, "rev-parse", "v1.0.0") == synced["commit"]


def test_version_mismatch_stops_before_touching_remote(repos):
    source, soota, product, _, baseline = repos
    (source / "src/lorelab/__init__.py").write_text('__version__ = "9.0.0"\n')
    commit(source)
    git(source, "push", "--quiet", str(product), "main")
    with pytest.raises(ValueError):
        publish(source, product_repository=str(product), execute=True)
    assert git(soota, "rev-parse", "main") == baseline
    assert not git(product, "tag")
