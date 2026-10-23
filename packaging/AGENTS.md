# packaging/

> L2 | 父级: [AGENTS.md](../AGENTS.md)

- `common.py`：明确的源码选择、组件 `verify(root)` 接口、bundle 文件校验和本机工具链。
- `build_release.py`：从本地源码构建 macOS arm64 Cubox、依赖 wheel 和 tar.gz；输出校验文件。
- `install.py`：隔离构建 release，生成绝对路径 runtime、五个命令和 Skills；检查后原子切换 current。
- `uv.sh`：复用已安装 uv，或引导固定版 uv；不修改 shell profile。
- `requirements.lock`：Python 3.12 运行依赖的精确版本与分发文件 SHA256。
- `build-requirements.in` / `build-requirements.lock`：构建后端、pip 等构建依赖的输入和哈希锁。

新包名与主命令为 `lorelab`，旧 `lorehub` 命令转入同一模块；Soota 与三个独立组件入口保留。Python wheel 同时包含 `lorelab` 和 `lorehub`，依赖的 Soota wheel 只由 `modules/soota` 构建，不从发行索引补取。旧 LoreHub bundle 仍按原文件清单校验，旧 prefix 可以升级；回退不改写旧 release。

launcher 同时注入一致的 `LORELAB_ROOT/LOREHUB_ROOT`、`LORELAB_RUNTIME_FILE/LOREHUB_RUNTIME_FILE`。Soota 独立读取 `SOOTA_KNOWLEDGE_RUNTIME_FILE` 与 `SOOTA_KNOWLEDGE_COMPONENTS_LOCK`；清单含 `source_root`、`components_lock`、锁指纹及固定工具路径。产品运行时拒绝不一致或跨组拼接的新旧变量，配置方法只委派 `soota.knowledge.runtime`。

构建产物 `prebuilt/`、`wheels/`、`bundle.json` 只在临时源码副本内生成，不提交。
使用与恢复步骤见 [installation.md](../docs/installation.md)。组件指纹算法只属于 `src/lorelab/components.py`；`src/lorehub/components.py` 是同一模块的兼容入口。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
