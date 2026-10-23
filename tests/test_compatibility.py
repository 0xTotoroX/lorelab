"""撤掉旧命令后，Soota 与 LoreLab 仍可读取冻结任务，不重写历史授权。"""

import json
import os
import subprocess
import sys
from pathlib import Path

from soota.cli import app
from typer.testing import CliRunner

from lorelab.cli import main
from lorelab.knowledge.workflow_state import save, seal


def test_current_entrypoints_read_old_frozen_job_without_migration(tmp_path, capsys, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(root / "src"), str(root / "modules/soota/src")]))
    job = tmp_path / "old-job"
    job.mkdir()
    state = {"schema_version": 1, "job": str(job), "status": "waiting_review", "sealed": {}}
    # 历史任务没有 with_outline/source_kind；缺字段须按原来的组合交付继续。
    seal(job, state, "spec.json", {"ids": [], "delete_verified": True})
    seal(job, state, "sources.json", [])
    seal(job, state, "handoffs.json", {})
    save(job, state)
    before = {p.name: p.read_bytes() for p in job.iterdir()}
    assert main(["batch", "status", str(job)]) == 0
    product_status = json.loads(capsys.readouterr().out)
    result = CliRunner().invoke(app, ["knowledge", "status", str(job)])
    assert result.exit_code == 0, result.output
    assert product_status == json.loads(result.stdout)
    assert product_status["delivery"] == "article-and-outline"
    assert product_status["source_kind"] == "cubox"
    assert {name: (job / name).read_bytes() for name in before} == before


def test_removed_python_command_cannot_execute_from_source(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    result = subprocess.run(
        [sys.executable, "-S", "-m", "lorehub.cli", "--help"],
        env={**os.environ, "PYTHONPATH": str(source)},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "No module named" in result.stderr
