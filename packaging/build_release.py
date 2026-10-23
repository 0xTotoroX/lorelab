#!/usr/bin/env python3
"""创建包含本地组件源码、Cubox 和依赖 wheel 的发行包。

[INPUT]: 完整产品源码、固定依赖锁、Go、uv。
[OUTPUT]: macOS arm64 tar.gz 和 SHA256 文件。
[POS]: packaging 的发布者入口；不写入源码树或云端。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import argparse
import gzip
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    PackagingError,
    build_payload,
    copy_source,
    get_uv,
    platform_tag,
    seal_bundle,
    sha256,
    source_files,
    verify_bundle,
    verify_inputs,
)


def build(root: Path, output_dir: Path) -> Path:
    root = root.resolve()
    verify_inputs(root)
    files = source_files(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lorehub-build-") as temporary:
        work = Path(temporary)
        source = work / "source"
        copy_source(root, source, files)
        verify_inputs(source)
        uv = get_uv(source, work / "bootstrap")
        build_payload(source, work / "toolchain", uv)
        # 构建后再次校验组件，构建工具不能悄悄改写锁定源码。
        verify_inputs(source)
        bundle = seal_bundle(source)
        verify_bundle(source)
        name = f"lorehub-{bundle['release_id']}-{platform_tag()}"
        output = output_dir / f"{name}.tar.gz"
        if output.exists():
            raise PackagingError(f"refusing to overwrite release: {output}")
        pending = output.with_suffix(".tmp")
        try:
            with pending.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w") as archive:
                    for entry in sorted([*bundle["files"], "packaging/bundle.json"]):
                        path = source / entry
                        info = archive.gettarinfo(str(path), arcname=f"{name}/{entry}")
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
            os.replace(pending, output)
        finally:
            pending.unlink(missing_ok=True)
        output.with_name(output.name + ".sha256").write_text(f"{sha256(output)}  {output.name}\n")
        return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build(args.root, args.output_dir.expanduser().resolve()))
        return 0
    except (PackagingError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
