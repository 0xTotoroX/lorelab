"""[INPUT]: 受管 prefix 和 Windows 当前用户 PATH。
[OUTPUT]: 可回退的用户 PATH 更新；激活成功后通知桌面，不修改机器范围配置。
[POS]: setup 的 Windows 路径适配；仅在原生 Windows 导入注册表模块。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

import contextlib
import ctypes
import os
import sys


def notify_environment():
    # HWND_BROADCAST / WM_SETTINGCHANGE；指针宽度同时兼容 Windows x64 和 arm64。
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send = user32.SendMessageTimeoutW
    send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_wchar_p,
                     ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    send.restype = ctypes.c_ssize_t
    result = ctypes.c_size_t()
    if not send(0xFFFF, 0x001A, 0, "Environment", 0x0002, 1000, ctypes.byref(result)):
        raise OSError("Windows 环境变更通知超时或失败")


@contextlib.contextmanager
def user_path(prefix, enabled=True):
    if os.name != "nt" or not enabled:
        yield False
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            original, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            original, kind = None, winreg.REG_EXPAND_SZ
        if original is not None and not isinstance(original, str):
            raise ValueError("用户 PATH 不是字符串，保留原配置。")
        entry = str(prefix / "bin")
        paths = (original or "").split(";")
        changed = entry.casefold().rstrip("\\") not in {p.casefold().rstrip("\\") for p in paths}
        if changed:
            value = (original or "") + (";" if original and not original.endswith(";") else "") + entry
            winreg.SetValueEx(key, "Path", 0, kind, value)
        try:
            yield changed
        except BaseException:
            if changed:
                if original is None:
                    winreg.DeleteValue(key, "Path")
                else:
                    winreg.SetValueEx(key, "Path", 0, kind, original)
            raise
        else:
            if changed:
                try:
                    notify_environment()
                except OSError as error:
                    # current 已提交；通知失败只影响桌面进程刷新，不能撤销安装或配置。
                    print(f"用户 PATH 已保存，但未能通知桌面：{error}；请加载 env.ps1 或重新登录。", file=sys.stderr)
