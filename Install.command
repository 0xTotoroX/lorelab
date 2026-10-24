#!/bin/sh
# Finder 入口与终端共用安装器；配置由 setup 引导，不另建安装实现。
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sh "$root/install.sh" "$@"
printf '\n安装完成。按输出中的绝对路径运行 lorelab setup，选择知识库并设置命令路径。\n'
