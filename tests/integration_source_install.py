"""在隔离用户目录实跑源码首次安装、重复执行、Git 升级与配置/任务保留。

命令：python tests/integration_source_install.py --workdir /path/to/empty-directory
日志只写指定目录；不查询账号或执行云端写入。
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
from common import copy_source, source_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--system-path", action="store_true", help="仅保留系统工具和 Git，验证无 uv/Go 的冷启动")
    parser.add_argument("--windows-code-page", type=int, help="Windows 安装前设定控制台代码页，验证非 UTF-8 环境")
    args = parser.parse_args()
    base = args.workdir.resolve()
    base.mkdir(parents=True, exist_ok=False)
    root = args.root.resolve()
    checkout = base / "source"
    copy_source(root, checkout, source_files(root))
    home = base / "user 中文 & space's"
    home.mkdir()
    prefix = home / ".local/share/lorelab"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LORELAB_", "LOREHUB_", "SOOTA_", "UV_", "PIP_", "PYTHON"))}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "roaming"),
               LOCALAPPDATA=str(home / "local"), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
               XDG_CACHE_HOME=str(home / ".cache"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    windows = sys.platform == "win32"
    if args.system_path:
        if windows:
            git = shutil.which("git", path=env.get("PATH"))
            if not git:
                raise RuntimeError("Git is required before source installation")
            # os.environ retains Windows' case-insensitive lookup; a plain dict does not.
            system = Path(os.environ["SystemRoot"]) / "System32"
            env["PATH"] = os.pathsep.join(map(str, [system, system / "WindowsPowerShell/v1.0", Path(git).parent]))
            # Do not inherit PowerShell 7's module search path into Windows PowerShell 5.1.
            env["PSMODULEPATH"] = str(system / "WindowsPowerShell/v1.0/Modules")
        else:
            env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    results = {}

    def run(name, command, *, cwd=checkout, expect=0):
        start = time.monotonic()
        with (base / (name + ".stdout")).open("w", encoding="utf-8") as out, \
             (base / (name + ".stderr")).open("w", encoding="utf-8") as err:
            completed = subprocess.run(list(map(str, command)), cwd=cwd, env=env, stdout=out, stderr=err, check=False)
        results[name] = {"seconds": round(time.monotonic() - start, 2), "exit_code": completed.returncode}
        (base / "progress.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        if completed.returncode != expect:
            raise RuntimeError(f"{name} returned {completed.returncode}; see {base / (name + '.stderr')}")
        return (base / (name + ".stdout")).read_text(encoding="utf-8")

    def commit(label):
        run(label + "-add", ["git", "add", "."])
        run(label + "-commit", ["git", "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid",
                                "commit", "-qm", label])

    run("git-init", ["git", "init", "-q", "-b", "main"])
    commit("initial")
    entry = (["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", checkout / "install.ps1"]
             if windows else ["/bin/sh", checkout / "install.sh"])
    if windows and args.windows_code_page:
        wrapper = base / "legacy-code-page.ps1"
        wrapper.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$originalCodePage = [Console]::OutputEncoding.CodePage\n"
            "try {\n"
            f"  & chcp.com {args.windows_code_page} | Out-Null\n"
            "  if ($LASTEXITCODE -ne 0) { throw 'Cannot select the test code page' }\n"
            "  & (Join-Path $PSScriptRoot 'source\\install.ps1') @args\n"
            "  $installExitCode = $LASTEXITCODE\n"
            "} finally { & chcp.com $originalCodePage | Out-Null }\n"
            "exit $installExitCode\n", encoding="ascii")
        entry[-1] = wrapper
    run("first-install", [*entry, "--prefix", prefix])
    first = (prefix / "current").resolve()
    cli = prefix / "bin" / ("lorelab.exe" if windows else "lorelab")
    soota = prefix / "bin" / ("soota.exe" if windows else "soota")
    run("repeat-install", [*entry, "--prefix", prefix])
    assert (prefix / "current").resolve() == first
    vault = home / "知识库"
    vault.mkdir()
    run("setup", [cli, "setup", "--non-interactive", "--shell-profile", "none", "--vault", vault, "--subdir", "知识"])
    assert json.loads(run("doctor", [cli, "doctor"]))["ok"]
    content = home / "source.txt"
    content.write_text("保存原文：工具经验测试，不做语义改写。\n", encoding="utf-8")
    run("ingest", [soota, "ingest", content, "--want", "context", "--max-cost", "0", "--json"])
    config = home / ".config/lorelab/config.json"
    retained = [p for p in home.rglob("*") if p.is_file() and not p.is_relative_to(prefix)
                and not any(part in {".cache", "Caches", "__pycache__"} for part in p.parts)
                and not p.is_relative_to(home / ".agents") and not p.is_relative_to(home / ".local/bin")]
    # Go 的本地构建计数会随编译变化，不属于 CLI 配置、任务或内容产物。
    telemetry_roots = [home / "Library/Application Support/go/telemetry",
                       home / "roaming/go/telemetry", home / "local/go/telemetry", home / ".config/go/telemetry"]
    counters = [p for p in retained if any(p.is_relative_to(folder) for folder in telemetry_roots)]
    retained = [p for p in retained if p not in counters]
    assert config in retained

    def snapshot(files=retained):
        return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files}

    before = snapshot()
    counters_before = snapshot(counters)
    (base / "data-before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
    run("repeat-setup", [cli, "setup", "--non-interactive", "--shell-profile", "none"])
    assert snapshot() == before
    (checkout / "docs/acceptance-fixture.md").write_text("Synthetic upgrade fixture.\n", encoding="utf-8")
    commit("upgrade")
    # 开发工作区有未提交修改，Git 更新仍只安装所选提交。
    marker = checkout / "README.md"
    marker.write_text(marker.read_text(encoding="utf-8") + "\nUncommitted fixture.\n", encoding="utf-8")
    dirty = marker.read_bytes()
    assert json.loads(run("update-check", [cli, "update", "--check"]))["available"]
    assert json.loads(run("update", [cli, "update"]))["changed"]
    second = (prefix / "current").resolve()
    assert second != first and first.is_dir()
    assert json.loads(run("updated-doctor", [cli, "doctor"]))["ok"]
    assert not json.loads(run("repeat-update", [cli, "update"]))["changed"]
    run("bad-ref", [cli, "update", "--ref", "missing-fixture-branch"], expect=1)
    assert (prefix / "current").resolve() == second
    after = snapshot()
    (base / "data-after.json").write_text(json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8")
    assert marker.read_bytes() == dirty
    assert after == before, "Configuration/task changes: " + str([p for p in before if before[p] != after[p]])
    for name in ("lorelab", "soota", "cubox", "mubu-integration"):
        assert (home / ".agents/skills" / name / "SKILL.md").is_file()
    results.update(first_release=str(first), final_release=str(second), preserved_files=len(retained),
                   platform=sys.platform, cloud_writes=0,
                   build_counter_changes=[p for p, value in snapshot(counters).items() if counters_before[p] != value])
    (base / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
