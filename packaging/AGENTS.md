# packaging/

> L2 | 父级: [AGENTS.md](../AGENTS.md)

- `common.py`：明确的源码选择、组件 `verify(root)` 接口、bundle 文件校验和本机工具链。
- `build_release.py`：从本地源码构建 macOS arm64 Cubox、依赖 wheel 和 tar.gz；输出校验文件。
- `install.py`：隔离构建 release，生成绝对路径 runtime、四个命令和 Skills；检查后原子切换 current。
- `uv.sh`：复用已安装 uv，或引导固定版 uv；不修改 shell profile。
- `requirements.lock`：Python 3.12 运行依赖的精确版本与分发文件 SHA256。
- `build-requirements.in` / `build-requirements.lock`：构建后端、pip 等构建依赖的输入和哈希锁。

构建产物 `prebuilt/`、`wheels/`、`bundle.json` 只在临时源码副本内生成，不提交。
使用与恢复步骤见 [installation.md](../docs/installation.md)。组件指纹算法只属于 `src/lorehub/components.py`。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
