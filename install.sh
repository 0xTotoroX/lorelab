#!/bin/sh
# [INPUT]: 解压后的发行包或源码、--prefix 与可选 --skills-dir。
# [OUTPUT]: 用 uv 管理的 Python 调用 packaging/install.py。
# [POS]: 无需预装 Python/Go 的发行包引导入口。
# [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bootstrap=$(mktemp -d "${TMPDIR:-/tmp}/lorelab-bootstrap.XXXXXXXX")
trap 'rm -rf "$bootstrap"' EXIT HUP INT TERM
uv=$(sh "$root/packaging/uv.sh" "$bootstrap/uv")
unset UV_PYTHON_PREFERENCE UV_PYTHON UV_MANAGED_PYTHON UV_NO_MANAGED_PYTHON UV_PYTHON_DOWNLOADS
export UV_PYTHON_INSTALL_DIR="$bootstrap/python"
export UV_CACHE_DIR="$bootstrap/cache"
export UV_PYTHON_INSTALL_BIN=false
"$uv" --no-config python install --no-bin 3.12.12
python=$("$uv" --no-config python find --managed-python 3.12.12)
LORELAB_INSTALL_UV="$uv" LOREHUB_INSTALL_UV="$uv" "$python" -I -B "$root/packaging/install.py" "$@"
