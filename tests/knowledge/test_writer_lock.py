"""目的地和幕布资源的真实互斥、固定加锁次序及异常释放。"""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from lorelab.knowledge import workflow_publish as publisher
from lorelab.knowledge.workflow_state import WorkflowError, digest


@pytest.fixture(autouse=True)
def isolated_locks(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def spec(destination, document=None):
    return {"destination": str(destination), "with_outline": document is not None, "mubu_doc": document}


def attempt_in_process(value):
    # 新解释器不能依赖父进程的线程锁，必须由文件锁阻止并发。
    script = """
import json
import sys
from lorelab.knowledge.workflow_publish import writer
from lorelab.knowledge.workflow_state import WorkflowError

try:
    with writer(json.loads(sys.argv[1])):
        print("entered")
except WorkflowError:
    print("blocked")
"""
    env = dict(os.environ, PYTHONPATH=str(Path(publisher.__file__).resolve().parents[2]))
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, json.dumps(value)],
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize(
    "held_root,held_doc,other_root,other_doc,expected",
    [
        ("A", None, "A", "doc", "blocked"),
        ("A", "doc", "A", None, "blocked"),
        ("A", "doc-1", "A", "doc-2", "blocked"),
        ("A", "doc", "B", "doc", "blocked"),
        ("A", None, "B", None, "entered"),
        ("A", "doc-1", "B", "doc-2", "entered"),
    ],
    ids=[
        "article-blocks-outline", "outline-blocks-article", "same-destination-different-documents",
        "same-document-different-destinations", "independent-articles", "independent-combined-deliveries",
    ],
)
def test_writer_resource_exclusion_across_processes(
    tmp_path, held_root, held_doc, other_root, other_doc, expected,
):
    held = spec(tmp_path / held_root, held_doc)
    contender = spec(tmp_path / other_root, other_doc)
    with publisher.writer(held):
        assert attempt_in_process(contender) == expected
    assert attempt_in_process(contender) == "entered"


def test_legacy_outline_job_holds_both_resources(tmp_path):
    legacy = spec(tmp_path / "A", "doc")
    legacy.pop("with_outline")
    with publisher.writer(legacy):
        assert attempt_in_process(spec(tmp_path / "A")) == "blocked"
        assert attempt_in_process(spec(tmp_path / "B", "doc")) == "blocked"


def test_document_lock_failure_releases_destination(tmp_path):
    with publisher.writer(spec(tmp_path / "A", "doc")):
        with pytest.raises(WorkflowError), publisher.writer(spec(tmp_path / "B", "doc")):
            pytest.fail("共享幕布仍被占用，不能进入写入区。")
        # 第二把锁失败后，目的地 B 应立即可用，且不影响原持有者。
        assert attempt_in_process(spec(tmp_path / "B")) == "entered"
        assert attempt_in_process(spec(tmp_path / "A")) == "blocked"


def test_body_failure_releases_both_resources(tmp_path):
    with pytest.raises(RuntimeError, match="interrupted"), publisher.writer(spec(tmp_path / "A", "doc")):
        raise RuntimeError("interrupted")
    assert attempt_in_process(spec(tmp_path / "A")) == "entered"
    assert attempt_in_process(spec(tmp_path / "B", "doc")) == "entered"


def test_destination_is_locked_before_attempting_document(tmp_path, monkeypatch):
    value = spec(tmp_path / "A", "doc")
    root = tmp_path / "state/lorehub/locks"
    article = root / ("article-" + digest(value["destination"].encode()) + ".lock")
    document = root / ("mubu-" + digest(value["mubu_doc"].encode()) + ".lock")
    real_lock = publisher.lock
    checked = []

    @contextmanager
    def check_order(path):
        if path == document:
            with pytest.raises(WorkflowError), real_lock(article):
                pytest.fail("取得幕布锁之前，必须已持有文章目的地锁。")
            checked.append(path)
        with real_lock(path):
            yield

    monkeypatch.setattr(publisher, "lock", check_order)
    with publisher.writer(value):
        pass
    assert checked == [document]


def test_existing_document_lock_still_blocks_combined_delivery(tmp_path):
    # 保留旧幕布锁命名空间，已启动的旧入口仍能阻止新组合交付。
    document = tmp_path / "state/lorehub/locks" / ("mubu-" + digest(b"doc") + ".lock")
    with publisher.lock(document):
        assert attempt_in_process(spec(tmp_path / "A", "doc")) == "blocked"
        assert attempt_in_process(spec(tmp_path / "A")) == "entered"
