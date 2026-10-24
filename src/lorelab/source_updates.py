"""[INPUT]: 受管安装记录、明确的源码目录或 Git 仓库与 ref。
[OUTPUT]: 经来源检查的候选源码安装、内容比较与来源回执。
[POS]: Agent 驱动的源码更新；候选安装器处理平台与事务，不修改用户工作区。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def update_source(args, prefix, before, install):
    # installer() 已加载其依赖；源码接口沿用同一个 packaging 主源。
    from repository import fingerprint, provenance, snapshot

    saved = install.settings(prefix).get("source", {})
    repository = getattr(args, "repo", None) or saved.get("repository")
    ref = getattr(args, "ref", None) or saved.get("ref") or "HEAD"

    def apply(root, origin):
        install.verify_inputs(root)
        identity = fingerprint(root)
        previous = json.loads((before / "runtime.json").read_text(encoding="utf-8"))
        if args.check:
            return {"ok": True, "available": previous.get("source_fingerprint") != identity,
                    "source_fingerprint": identity, "source": origin, "installed": False}
        # 仓库是用户授权的代码来源。使用候选安装器，使安装器修正本身也在本次升级生效。
        with tempfile.TemporaryDirectory(prefix="lorelab-origin-") as temporary:
            command = [sys.executable, "-X", "utf8", "-I", "-B", str(root / "packaging/install.py"),
                       "--prefix", str(prefix), "--no-skills", "--no-bin"]
            if origin:
                receipt = Path(temporary) / "origin.json"
                receipt.write_text(json.dumps(origin), encoding="utf-8")
                command += ["--source-origin", str(receipt)]
            if args.force:
                command.append("--force")
            subprocess.run(command, env={**os.environ, "PYTHONUTF8": "1"}, stdout=sys.stderr, check=True)
        release = (prefix / "current").resolve()
        return {"ok": True, "changed": release != before, "release": str(release),
                "source_fingerprint": identity, "source": origin, "configuration_and_tasks": "preserved"}

    if args.source:
        root = Path(args.source).expanduser().resolve()
        return apply(root, provenance(root))
    if not repository:
        raise ValueError("没有源码仓库记录；请使用 lorelab update --from 本地仓库，或 --repo 仓库地址 --ref 分支。")
    # Git cache 的 FETCH_HEAD 同样需要互斥；不锁安装 prefix，以免候选安装器死锁。
    cache = prefix / "toolchain/repositories"
    cache.mkdir(parents=True, exist_ok=True)
    from platform_support import exclusive_lock

    with exclusive_lock(cache / ".fetch.lock"), snapshot(repository, ref, cache) as (root, origin):
        return apply(root, origin)
