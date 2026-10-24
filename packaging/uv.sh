#!/bin/sh
# [INPUT]: 已安装 uv，或固定版本官方安装脚本。
# [OUTPUT]: stdout 只输出 uv 绝对路径；不修改 shell profile。
# [POS]: install.sh 与 Python 构建/安装器共用的引导入口。
# [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
set -eu
dest=$1
if [ -x "$dest/uv" ]; then
    printf '%s\n' "$dest/uv"
    exit 0
fi
if command -v uv >/dev/null 2>&1; then
    command -v uv
    exit 0
fi
mkdir -p "$dest"
script="$dest/install-uv.sh"
curl --proto '=https' --tlsv1.2 -fsSL https://astral.sh/uv/0.9.26/install.sh -o "$script"
expected=09ace6a888bd5941b5d44f1177a9a8a6145552ec8aa81c51b1b57ff73e6b9e18
if command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$script" | cut -d ' ' -f 1)
else
    actual=$(sha256sum "$script" | cut -d ' ' -f 1)
fi
if [ "$actual" != "$expected" ]; then
    echo 'uv bootstrap checksum mismatch' >&2
    exit 1
fi
UV_UNMANAGED_INSTALL="$dest" UV_NO_MODIFY_PATH=1 sh "$script" >&2
printf '%s\n' "$dest/uv"
