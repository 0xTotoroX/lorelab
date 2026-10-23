"""旧 Python 导入、命令和冻结任务共享 Soota 实现，不重写历史授权。"""

import importlib
import json

import pytest
from soota.cli import app
from soota.knowledge.workflow_state import save, seal
from typer.testing import CliRunner


@pytest.mark.parametrize(
    "module",
    [
        "workflow",
        "workflow_sources",
        "workflow_review",
        "workflow_publish",
        "workflow_cleanup",
        "workflow_state",
        "study",
    ],
)
def test_old_python_modules_are_the_same_soota_implementation(module):
    assert importlib.import_module("lorehub." + module) is importlib.import_module("soota.knowledge." + module)


def test_all_entrypoints_read_old_frozen_job_without_migration(tmp_path, capsys):
    job = tmp_path / "old-job"
    job.mkdir()
    state = {"schema_version": 1, "job": str(job), "status": "waiting_review", "sealed": {}}
    # 历史任务没有 with_outline/source_kind；缺字段须按原来的组合交付继续。
    seal(job, state, "spec.json", {"ids": [], "delete_verified": True})
    seal(job, state, "sources.json", [])
    seal(job, state, "handoffs.json", {})
    save(job, state)
    before = {p.name: p.read_bytes() for p in job.iterdir()}
    values = []
    for module in ("lorehub.cli", "lorelab.cli"):
        assert importlib.import_module(module).main(["batch", "status", str(job)]) == 0
        values.append(json.loads(capsys.readouterr().out))
    result = CliRunner().invoke(app, ["knowledge", "status", str(job)])
    assert result.exit_code == 0, result.output
    values.append(json.loads(result.stdout))
    assert values[0] == values[1] == values[2]
    assert values[0]["delivery"] == "article-and-outline"
    assert values[0]["source_kind"] == "cubox"
    assert {name: (job / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("command", ["init", "batch", "study"])
def test_old_parser_uses_the_canonical_product_parser(command):
    from lorehub import cli as old
    from lorelab import cli as new

    assert old is new
    argv = {
        "init": ["init", "--vault", "/example", "--subdir", "Knowledge"],
        "batch": ["batch", "status", "/example/job"],
        "study": ["study", "status", "/example/study"],
    }[command]
    assert vars(old.parser().parse_args(argv)) == vars(new.parser().parse_args(argv))
