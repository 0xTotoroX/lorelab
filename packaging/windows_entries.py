"""[INPUT]: 已构建的原生 launcher、受管命令路径。
[OUTPUT]: 独占创建 Windows .exe / JSON；激活失败仅按本事务持有的句柄回滚。
[POS]: Windows 命令注册事务，目录 Skill 仍使用 junction。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import contextlib
import ctypes
import hashlib
import json
import os
import stat
from pathlib import Path

from common import sha256


def owned(path, target):
    sidecar = Path(str(path) + ".json")
    try:
        # 包括悬空链接在内，任何链接或目录都不能冒充受管普通文件。
        if not all(stat.S_ISREG(p.lstat().st_mode) for p in (path, sidecar)):
            return False
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        return (isinstance(value, dict) and value.get("lorelab_launcher") == 1
                and value.get("command") == [str(target)] and value.get("environment") == {}
                and value.get("sha256") == sha256(path))
    except (OSError, ValueError, TypeError):
        return False


def _kernel32():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                 wintypes.LPVOID, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _delete_handle(kernel, handle):
    # FILE_DISPOSITION_INFO.DeleteFile 是单字节 BOOLEAN；删除绑定到文件句柄而非路径。
    delete = ctypes.c_ubyte(1)
    if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
        raise ctypes.WinError(ctypes.get_last_error())


def _open_exclusive(path):
    if os.name != "nt":
        return path.open("x+b", buffering=0)
    import msvcrt

    kernel = _kernel32()
    # CREATE_NEW 拒绝包括悬空链接在内的已有目录项。零共享禁止写入、替换和删除，
    # 持有 DELETE 权限直到整个激活事务结束，失败时无需关闭句柄再按路径删除。
    handle = kernel.CreateFileW(str(path), 0xC0010000, 0, None, 1, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        try:
            _delete_handle(kernel, handle)
        finally:
            kernel.CloseHandle(handle)
        raise
    try:
        return os.fdopen(descriptor, "r+b", buffering=0)
    except BaseException:
        try:
            _delete_handle(kernel, handle)
        finally:
            os.close(descriptor)
        raise


class Registration:
    """持有新建文件；正常退出释放句柄，异常退出仅清理本次创建的文件。"""

    def __init__(self):
        self.files = []

    def write(self, path, data):
        stream = _open_exclusive(path)
        self.files.append((path, stream))
        remaining = memoryview(data)
        while remaining:
            written = stream.write(remaining)
            if not written:
                raise OSError(f"incomplete command registration: {path}")
            remaining = remaining[written:]

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            if kind is not None:
                self.rollback()
        finally:
            self.close()

    def close(self):
        for _, stream in self.files:
            # 激活提交后的句柄释放不能把成功安装变成失败并删除已激活的 release。
            with contextlib.suppress(OSError):
                stream.close()

    def rollback(self):
        failures = []
        for path, stream in reversed(self.files):
            if stream.closed:
                continue
            try:
                if os.name == "nt":
                    import msvcrt

                    _delete_handle(_kernel32(), msvcrt.get_osfhandle(stream.fileno()))
                else:
                    # 非 Windows 仅供本地模拟；保留句柄防止 inode 被复用，拒删替换项。
                    with contextlib.suppress(FileNotFoundError):
                        if os.path.samestat(os.fstat(stream.fileno()), path.lstat()):
                            path.unlink()
            except OSError as error:
                failures.append(error)
        if failures:
            raise failures[0]


def create(path, target, launcher):
    sidecar = Path(str(path) + ".json")
    if os.path.lexists(path) or os.path.lexists(sidecar):
        raise FileExistsError(f"refusing existing command or sidecar: {path}")
    binary = launcher.read_bytes()
    config = {"lorelab_launcher": 1, "command": [str(target)], "environment": {},
              "sha256": hashlib.sha256(binary).hexdigest()}
    registration = Registration()
    try:
        registration.write(path, binary)
        registration.write(sidecar, (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except BaseException:
        try:
            registration.rollback()
        finally:
            registration.close()
        raise
    return registration
