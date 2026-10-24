"""隔离验收唯一主源修改、历史同步、配对发布和两种安装方式的升级。

仅操作 --workdir 内的本地 Git 目标，不发布 GitHub、不触碰真实账号或知识库。
需要主源已提交；默认沿用组件导入历史，也可指定 --standalone-start 验证较旧远端。
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--standalone-start")
    args = parser.parse_args()
    base = args.workdir.resolve()
    base.mkdir(parents=True, exist_ok=False)
    home = base / "user 中文"
    home.mkdir()
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required for the independent Soota installation test")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LORELAB_", "LOREHUB_", "SOOTA_", "PYTHON", "UV_", "PIP_", "GIT_"))}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "roaming"),
               LOCALAPPDATA=str(home / "local"), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
               XDG_CACHE_HOME=str(home / ".cache"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               SOOTA_OUTPUT_DIR=str(home / "content"), SOOTA_AUTO_UPDATE="false")
    results = {}

    def run(name, command, cwd=None, *, expect=0):
        started = time.monotonic()
        with (base / f"{name}.stdout").open("w", encoding="utf-8") as out, \
                (base / f"{name}.stderr").open("w", encoding="utf-8") as err:
            completed = subprocess.run(list(map(str, command)), cwd=cwd or base, env=env,
                                       stdout=out, stderr=err, check=False)
        results[name] = {"seconds": round(time.monotonic() - started, 2), "exit_code": completed.returncode}
        (base / "progress.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        if completed.returncode != expect:
            raise RuntimeError(f"{name}: exit {completed.returncode}; inspect {base / (name + '.stderr')}")
        return (base / f"{name}.stdout").read_text(encoding="utf-8")

    def commit(name):
        run(name + "-add", ["git", "add", "."], source)
        run(name + "-commit", ["git", "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid",
                              "-c", "commit.gpgsign=false", "commit", "-qm", name], source)

    windows = os.name == "nt"
    source = base / "lorelab-source"
    run("clone-product", ["git", "clone", "--no-hardlinks", args.root.resolve(), source])
    product = base / "lorelab.git"
    run("product-remote", ["git", "clone", "--bare", source, product])
    run("bind-product-remote", ["git", "remote", "set-url", "origin", product], source)
    manifest = json.loads((source / "components.lock.json").read_text(encoding="utf-8"))
    baseline = manifest["components"]["soota"]["revision"]
    original = args.standalone_start or baseline
    soota = base / "soota.git"
    soota.mkdir()
    run("soota-remote", ["git", "init", "--bare", "--initial-branch=main", soota])
    run("original-history", ["git", "fetch", "--no-tags", source, baseline], soota)
    run("original-ancestor", ["git", "merge-base", "--is-ancestor", original, baseline], soota)
    run("original-ref", ["git", "update-ref", "refs/heads/main", original], soota)
    # 直接用检验源的 Python 执行 CLI；子命令通过 --source 固定被验收的 checkout。
    driver = [sys.executable, "-m", "lorelab.cli"]
    command_env_path = str(args.root.resolve() / "src") + os.pathsep + str(args.root.resolve() / "modules/soota/src")
    env["PYTHONPATH"] = command_env_path
    first_sync = json.loads(run("first-sync", [*driver, "components", "sync", "soota", "--source", source,
                                               "--repository", soota, "--execute"]))
    run("history-preserved", ["git", "merge-base", "--is-ancestor", baseline, first_sync["commit"]], soota)
    standalone = base / "standalone"
    run("clone-standalone", ["git", "clone", soota, standalone])
    env.pop("PYTHONPATH")
    run("standalone-install", [uv, "sync", "--python", "3.12", "--locked", "--no-dev"], standalone)
    vbin = "Scripts" if windows else "bin"
    python_name = "python.exe" if windows else "python"
    cli_name = "soota.exe" if windows else "soota"
    independent_python = standalone / ".venv" / vbin / python_name
    independent_cli = standalone / ".venv" / vbin / cli_name
    run("standalone-is-independent", [independent_python, "-c",
         "import importlib.util; assert importlib.util.find_spec('lorelab') is None"])
    text = home / "source.txt"
    text.write_text("保留原文与原任务：统一源码升级验收。\n", encoding="utf-8")
    run("standalone-ingest", [independent_cli, "ingest", text, "--want", "context", "--max-cost", "0", "--json"])
    saved = home / ".config/soota/preserved.txt"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text("Existing configuration stays intact", encoding="utf-8")
    prefix = home / ".local/share/lorelab"
    entry = (["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", source / "install.ps1"]
             if windows else ["/bin/sh", source / "install.sh"])
    run("lorelab-install", [*entry, "--prefix", prefix, "--bin-dir", home / "bin", "--skills-dir", home / "skills"])
    managed_cli = prefix / "bin" / ("lorelab.exe" if windows else "lorelab")
    managed_soota = prefix / "bin" / cli_name
    first_release = (prefix / "current").resolve()
    run("managed-ingest", [managed_soota, "ingest", text, "--want", "context", "--max-cost", "0", "--json"])

    def fingerprint(path):
        return [hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns]

    retained = {str(p): fingerprint(p) for folder in [home / "content", home / ".config/soota", home / ".local/state/soota"]
                if folder.exists() for p in folder.rglob("*") if p.is_file()}
    (base / "retained-before.json").write_text(json.dumps(retained, indent=2), encoding="utf-8")
    component = source / "modules/soota"
    marker = "single-source-upgrade-verified"
    init = component / "src/soota/__init__.py"
    init.write_text(init.read_text(encoding="utf-8") + f'\nSYNC_ACCEPTANCE_MARKER = "{marker}"\n', encoding="utf-8")
    skill = component / "skills/soota/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nSynthetic upgrade marker: " + marker + "\n", encoding="utf-8")
    import tomllib

    def bump(path):
        version = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
        major, minor, patch = map(int, version.split("."))
        return f"{major}.{minor}.{patch + 1}"

    product_version, soota_version = bump(source / "pyproject.toml"), bump(component / "pyproject.toml")
    env["PYTHONPATH"] = command_env_path
    run("prepare-versions", [*driver, "release", "prepare", "--source", source,
                             "--version", product_version, "--soota-version", soota_version])
    commit("single-source-change")
    run("publish-reviewed-source", ["git", "push", "origin", "main"], source)
    synchronized = json.loads(run("sync-change", [*driver, "components", "sync", "soota", "--source", source,
                                                    "--repository", soota, "--execute"]))
    publication = [*driver, "release", "publish", "--source", source, "--repository", product,
                   "--soota-repository", soota]
    run("release-preview", publication)
    released = json.loads(run("paired-release", [*publication, "--execute"]))
    repeated = json.loads(run("repeat-release", [*publication, "--execute"]))
    assert repeated["soota"]["commit"] == released["soota"]["commit"] == synchronized["commit"]
    assert not repeated["soota"]["changed"]
    env.pop("PYTHONPATH")
    run("standalone-pull", ["git", "pull", "--ff-only"], standalone)
    run("standalone-upgrade", [uv, "sync", "--python", "3.12", "--locked", "--no-dev"], standalone)
    check = json.loads(run("lorelab-update-check", [managed_cli, "update", "--check"]))
    assert check["available"]
    upgrade = json.loads(run("lorelab-upgrade", [managed_cli, "update"]))
    assert upgrade["changed"] and (prefix / "current").resolve() != first_release and first_release.exists()
    assert json.loads(run("lorelab-repeat-update", [managed_cli, "update"]))["changed"] is False
    assert json.loads(run("doctor", [managed_cli, "doctor"]))["ok"]
    installed = (prefix / "current").resolve()
    managed_python = installed / "venv" / vbin / python_name
    for name, python in [("independent", independent_python), ("managed", managed_python)]:
        run(name + "-new-code", [python, "-c", ("import soota; "
            f"assert soota.__version__ == {soota_version!r}; assert soota.SYNC_ACCEPTANCE_MARKER == {marker!r}")])
    run("still-independent", [independent_python, "-c",
         "import importlib.util; assert importlib.util.find_spec('lorelab') is None"])
    runtime = json.loads((installed / "runtime.json").read_text(encoding="utf-8"))
    bound_component = Path(runtime["source_root"]) / "modules/soota"
    # 逐文件比对主源、独立发行和成套安装；回执自身不属于组件指纹。
    provenance = json.loads((standalone / "lorehub-provenance.json").read_text(encoding="utf-8"))
    for relative, expected in provenance["files"].items():
        for directory in [component, standalone, bound_component]:
            assert hashlib.sha256((directory / relative).read_bytes()).hexdigest() == expected, (directory, relative)
    assert (home / "skills/soota/SKILL.md").read_bytes() == skill.read_bytes()
    assert all(fingerprint(Path(p)) == value for p, value in retained.items())
    assert len(list((home / "content").rglob("context.md"))) >= 1
    result = {"ok": True, "platform": sys.platform, "steps": results, "versions": released["versions"],
              "source_commit": released["lorelab"]["commit"], "soota_commit": released["soota"]["commit"],
              "original_start": original, "original_import": baseline,
              "component_files_compared": len(provenance["files"]), "preserved_files": len(retained),
              "independent_without_lorelab": True, "old_managed_release_retained": True,
              "remote_scope": "local Git repositories only", "cloud_writes": 0}
    (base / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "steps"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
