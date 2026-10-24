"""[INPUT]: 本机 Go 或官方固定版本归档及哈希。
[OUTPUT]: 可复用的 Go 编译器，下载和构建缓存均位于安装 prefix。
[POS]: 源码安装的工具链引导；不需要系统级安装或管理员权限。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from common import PackagingError, sha256

VERSION = "1.27.3"
ARCHIVES = {
    "darwin-amd64": ("tar.gz", "b6f8e931e4ab497fcde6da8ae4499a58f9d258e55c8a80824a516eae5950a750"),
    "darwin-arm64": ("tar.gz", "dd3908cf20959d798c1e06ebe5b72213f0505ce01373b40ce3110975a6cd99c2"),
    "windows-amd64": ("zip", "f26081f438319757f8a1b46d7d0b2c5ec7583d4038e485e0aa725cfde7885fff"),
    "windows-arm64": ("zip", "c507872ff21f8a7cd3c1c217b059c6f7271a4a9d8e692810ef9dd3e1f601197c"),
}


def compatible(binary):
    try:
        result = subprocess.run([str(binary), "version"], capture_output=True, text=True, timeout=15, check=False)
        match = re.search(r"go(\d+)\.(\d+)", result.stdout)
        return result.returncode == 0 and match and tuple(map(int, match.groups())) >= (1, 23)
    except (OSError, subprocess.TimeoutExpired):
        return False


def get_go(directory: Path, target: str) -> Path:
    existing = shutil.which("go")
    if existing and compatible(existing):
        return Path(existing)
    folder = directory / f"go-{VERSION}-{target}"
    binary = folder / "go/bin" / ("go.exe" if target.startswith("windows-") else "go")
    if binary.is_file() and compatible(binary):
        return binary
    extension, expected = ARCHIVES[target]
    name = f"go{VERSION}.{target}.{extension}"
    cache = directory / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.is_file() or sha256(archive) != expected:
        pending = archive.with_suffix(archive.suffix + ".part")
        try:
            with urllib.request.urlopen("https://go.dev/dl/" + name, timeout=60) as response, pending.open("wb") as out:
                shutil.copyfileobj(response, out)
            if sha256(pending) != expected:
                raise PackagingError("Go download checksum mismatch")
            os.replace(pending, archive)
        finally:
            pending.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(dir=directory, prefix="go-extract-") as temp:
        if extension == "zip":
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(temp)
        else:
            with tarfile.open(archive) as tar:
                tar.extractall(temp, filter="data")
        os.replace(temp, folder)
    if not compatible(binary):
        raise PackagingError("downloaded Go cannot execute on this platform")
    return binary
