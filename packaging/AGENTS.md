# packaging/

> L2 | 父级: [AGENTS.md](../AGENTS.md)

- `common.py`：明确的源码选择、组件 `verify(root)` 接口、bundle 文件校验和本机工具链。
- `build_release.py`：从本地源码构建 macOS arm64 Cubox、依赖 wheel 和 tar.gz；输出校验文件。
- `build_plugin.py`：从同一 bundle 生成一个本地插件，含四套独立 Skill、引用闭包和配套 tar.gz；不上传或改宿主配置。
- `install.py`：隔离构建 release，生成绝对路径 runtime、四个命令和 Skills；检查后退役归属本 prefix 的旧入口并原子切换 current。
- `uv.sh`：复用已安装 uv，或引导固定版 uv；不修改 shell profile。
- `requirements.lock`：Python 3.12 运行依赖的精确版本与分发文件 SHA256。
- `build-requirements.in` / `build-requirements.lock`：构建后端、pip 等构建依赖的输入和哈希锁。

只分发 `lorelab`、`cubox-cli`、`soota`、`mubu-cli` 四个命令，以及 `lorelab`、`cubox`、`soota`、`mubu-integration` 四套 Skill。产品 Python wheel 包含 `lorelab` 与其 `knowledge/` 工作流，依赖的 Soota wheel 只由 `modules/soota` 构建，不从发行索引补取。源码选择排除 `src/lorehub`、`skills/lorehub`；bundle 拒绝这两类文件和旧产品 wheel。新安装器只接受 LoreLab 源码或 bundle；历史 LoreHub 包使用自身安装器。

既有 runtime 的 `product=lorehub` 或 `product=lorelab` 均可升级，旧 release 不改写。激活事务只删除直接指向本 prefix `current/bin/lorehub` 的 `bin/lorehub` 软链接，以及显式 `--skills-dir` 中指向本 prefix `current/skills/lorehub` 的旧 Skill 链接；规范化的链接文本与解析目标须同时匹配，防止其他软链接加 `..` 伪装归属。外部文件、目录或其他目标的链接保留；不扫描未指定的 Skill 目录。旧入口在 `current` 切换前移除，退役或切换失败时恢复其原始链接文本并移除本次新建入口，保留旧 `current`。

launcher 同时注入一致的 `LORELAB_ROOT/LOREHUB_ROOT`、`LORELAB_RUNTIME_FILE/LOREHUB_RUNTIME_FILE`。LoreLab 工作流兼容读取 `SOOTA_KNOWLEDGE_RUNTIME_FILE` 与 `SOOTA_KNOWLEDGE_COMPONENTS_LOCK`；清单含 `source_root`、`components_lock`、锁指纹及固定工具路径。产品运行时拒绝不一致或跨组拼接的新旧变量，配置方法只委派 `lorelab.knowledge.runtime`。

构建产物 `prebuilt/`、`wheels/`、`bundle.json` 只在临时源码副本内生成，不提交。
安装记录位于 prefix/install.json，保存外部命令与 Skill 注册目录及可选更新清单；激活时一起提交，失败恢复。相同内容先校验再复用 current，不创建新 release；固定 Python 与下载缓存在 prefix/toolchain，多 release 共享，各 release 仍有独立 venv。旧私有 Python 不迁移。根 install.sh 和 Install.command 是统一安装入口，setup 单独管理 PATH 和知识目的地。
使用与恢复步骤见 [installation.md](../docs/installation.md)。组件指纹算法只属于 `src/lorelab/components.py`。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
