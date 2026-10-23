"""[INPUT]: 私有 job 文件、固定目的地和 CLI JSON。
[OUTPUT]: 持久化、线程/进程锁、不可变文件及路径校验。
[POS]: workflow 共用的本地状态边界；不调用服务。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unicodedata
from contextlib import contextmanager
from pathlib import Path


class WorkflowError(RuntimeError):
    """契约或保全检查未通过；不会隐式重试写入。"""


def require(condition, message):
    if not condition:
        raise WorkflowError(message)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def read_json(path: Path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise WorkflowError(f"无法读取 JSON：{path}") from exc


def sync_dir(path: Path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(not path.is_symlink(), f"拒绝符号链接：{path}")
    fd, temporary = tempfile.mkstemp(prefix=".lorehub-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, value):
    atomic(path, encoded(value))


def check_file(path: Path, sha: str):
    require(not path.is_symlink() and path.is_file(), f"缺失文件或符号链接：{path}")
    require(digest(path.read_bytes()) == sha, f"文件已修改：{path}")


def immutable(path: Path, data: bytes) -> str:
    sha = digest(data)
    if path.exists() or path.is_symlink():
        check_file(path, sha)
    else:
        atomic(path, data)
    return sha


def seal(job: Path, state: dict, name: str, value):
    state.setdefault("sealed", {})[name] = immutable(job / name, encoded(value))


def unseal(job: Path, state: dict, name: str):
    require(name in state.get("sealed", {}), f"状态尚未完成：{name}")
    check_file(job / name, state["sealed"][name])
    return read_json(job / name)


def save(job: Path, state: dict):
    write_json(job / "job.json", state)


def default_root() -> Path:
    return Path(os.environ.get("LOREHUB_STATE_DIR", str(Path.home() / ".local/state/lorehub/jobs"))).expanduser()


_thread_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


@contextmanager
def lock(path: Path):
    key = str(path.resolve())
    with _registry_lock:
        mutex = _thread_locks.setdefault(key, threading.Lock())
    require(mutex.acquire(blocking=False), "另一个操作正在执行；请等待当前写入者结束。")
    fd = None
    acquired = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(not path.is_symlink(), "锁文件不能是符号链接。")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except (BlockingIOError, PermissionError) as exc:
        raise WorkflowError("文件锁被占用或无法取得；未执行并发操作。") from exc
    finally:
        if fd is not None:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        mutex.release()


@contextmanager
def open_job(value: str):
    job = Path(value).expanduser()
    require(job.is_absolute() and job.is_dir() and not job.is_symlink(), "job 必须是现有状态目录的绝对路径。")
    job = job.resolve()
    with lock(job / ".lock"):
        state = read_json(job / "job.json")
        require(state.get("job") == str(job) and state.get("schema_version") == 1, "job 身份或版本不符。")
        for name, sha in state.get("sealed", {}).items():
            check_file(inside(job, name), sha)
        yield job, state


def parts(value: str):
    require(isinstance(value, str) and bool(value), "路径不能为空。")
    require(not Path(value).is_absolute() and "\\" not in value and ":" not in value, "拒绝绝对或跨平台歧义路径。")
    items = value.split("/")
    require(all(x and x not in {".", ".."} and not any(ord(c) < 32 for c in x) for x in items), "路径越界或无效。")
    return items


def inside(root: Path, relative: str) -> Path:
    target = root
    require(root.resolve() == root and root.is_dir() and not root.is_symlink(), f"根目录已改变：{root}")
    for item in parts(relative):
        target = target / item
        require(not target.is_symlink(), f"路径含符号链接：{target}")
    require(target.resolve().is_relative_to(root), "路径越界。")
    return target


def destination(spec: dict, relative: str | None = None) -> Path:
    vault = Path(spec["vault"])
    root = inside(vault, spec["subdir"]) if spec["subdir"] else vault
    require(str(root) == spec["destination"] and root.resolve() == root, "目的地已改变。")
    if relative is None:
        return root
    components = parts(relative)
    require(all(not p.startswith(".") for p in components), "拒绝隐藏目录或配置文件。")
    require(components[-1].casefold() not in {"agents.md", "claude.md"}, "拒绝覆盖目标规则文件。")
    require(Path(relative).suffix.lower() == ".md", "知识笔记必须是 Markdown 文件。")
    # 目的地可能尚不存在，仍逐级检查已有父目录中的符号链接。
    result = inside(vault, "/".join(filter(None, [spec["subdir"], relative])))
    return result


def path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def data(result):
    return result.get("data", result) if isinstance(result, dict) else result


def rows(result, label: str) -> list:
    result = data(result)
    # Cubox 对空查询返回 null。
    if result is None:
        return []
    require(isinstance(result, list), f"{label} 未返回完整数组。")
    require(all(isinstance(row, dict) for row in result), f"{label} 数组格式错误。")
    return result


def call(run, job: Path, tool: str, args: list[str], name: str, codes=(0,)):
    path = job / "receipts" / (name + ".json")
    result = run(tool, args, receipt=path, acceptable_codes=codes)
    # mock 或其他 runtime 也必须保留原始结果；写意图另行在调用前 fsync。
    write_json(path, result)
    return result


def mubu_args(spec: dict, *args: str) -> list[str]:
    return ["--agent", "--auth", spec["mubu_auth"], *args]
