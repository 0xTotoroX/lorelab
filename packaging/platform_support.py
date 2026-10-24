"""[INPUT]: 本机平台、受管路径和标准库文件操作。
[OUTPUT]: 平台路径、目录链接及进程锁；Windows 不需要开发者模式。
[POS]: 安装器的平台差异边界，保留 macOS 原安装布局。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import contextlib
import os
import sys
from pathlib import Path


def windows():
    return sys.platform == "win32"


def executable(name):
    return name + ".exe" if windows() else name


def venv_bin(venv: Path, name="python"):
    return venv / ("Scripts" if windows() else "bin") / executable(name)


def is_link(path):
    return path.is_symlink() or path.is_junction()


def link_target(path):
    target = os.readlink(path)
    target = target.removeprefix("\\\\?\\")
    return path.parent / target


def directory_link(path, target):
    if windows():
        # CPython 自带目录 junction，不调用 shell、不要求 symlink 特权。
        import _winapi

        _winapi.CreateJunction(str(Path(os.path.abspath(path.parent / target))), str(path))
    else:
        path.symlink_to(target, target_is_directory=True)


def remove_link(path):
    if path.is_junction():
        path.rmdir()
    else:
        path.unlink(missing_ok=True)


def switch_directory(pending, current):
    if not windows() or not os.path.lexists(current):
        os.replace(pending, current)
        return
    # Windows 不能覆盖已有目录 junction。持锁短暂改名，失败恢复原入口。
    backup = pending.with_name(pending.name + ".previous")
    os.replace(current, backup)
    try:
        os.replace(pending, current)
    except BaseException:
        os.replace(backup, current)
        raise
    # 激活之后的旧 junction 清理不能使已完成安装被当成失败删除。
    with contextlib.suppress(OSError):
        remove_link(backup)


@contextlib.contextmanager
def exclusive_lock(path):
    with path.open("a+b") as stream:
        if windows():
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
