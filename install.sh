#!/bin/sh
# [INPUT]: 解压后的发行包或源码、--prefix 与可选 --skills-dir。
# [OUTPUT]: 复用 prefix 的 Python/缓存，调用幂等安装器。
# [POS]: 无需预装 Python/Go 的发行包引导入口。
# [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
prefix="$HOME/.local/share/lorelab"
want_prefix=false
for argument in "$@"; do
    if [ "$want_prefix" = true ]; then prefix=$argument; want_prefix=false; continue; fi
    case "$argument" in
        --prefix) want_prefix=true ;;
        --prefix=*) prefix=${argument#--prefix=} ;;
        -h|--help)
            cat <<'HELP'
Usage: sh install.sh [--prefix DIR] [--skills-dir DIR | --no-skills]
                     [--bin-dir DIR] [--no-bin] [--force]
Installs four CLIs and four independent Skills on macOS arm64.
Defaults: ~/.local/share/lorelab, ~/.agents/skills, ~/.local/bin.
Existing registrations are retained on upgrade. Run lorelab setup afterwards.
HELP
            exit 0 ;;
    esac
done
if [ "$want_prefix" = true ] || [ -z "$prefix" ]; then
    echo '--prefix requires a directory' >&2; exit 2
fi
if [ "$(uname -s)/$(uname -m)" != 'Darwin/arm64' ]; then
    echo 'LoreLab bundles currently require macOS arm64; Android/Termux is not a supported runtime.' >&2
    exit 1
fi
# 已有安装直接运行 Python 安装器；相同包检查不需要下载 uv 或 Python。
if [ -x "$prefix/current/venv/bin/python" ]; then
    exec "$prefix/current/venv/bin/python" -I -B "$root/packaging/install.py" "$@"
fi
mkdir -p "$prefix/toolchain"
prefix=$(CDPATH= cd -- "$prefix" && pwd)
uv=$(sh "$root/packaging/uv.sh" "$prefix/toolchain/uv")
unset UV_PYTHON_PREFERENCE UV_PYTHON UV_MANAGED_PYTHON UV_NO_MANAGED_PYTHON UV_PYTHON_DOWNLOADS
export UV_PYTHON_INSTALL_DIR="$prefix/toolchain/python"
export UV_CACHE_DIR="$prefix/toolchain/cache"
export UV_PYTHON_INSTALL_BIN=false
"$uv" --no-config python install --no-bin 3.12.12
python=$("$uv" --no-config python find --managed-python 3.12.12)
LORELAB_INSTALL_UV="$uv" LOREHUB_INSTALL_UV="$uv" "$python" -I -B "$root/packaging/install.py" "$@"
