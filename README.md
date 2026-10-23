# LoreHub

把 Cubox 收藏整理成完整、连贯的文章，保存到 Obsidian 或用户明确指定的知识目录，回读核对后结束。需要学习或复习时，再从选定的文章制作幕布大纲。

一篇文章可以综合多个来源，讲清概念、关系和适用条件。完整意味着内容足够、自成一体，不要求篇幅长、修辞多或固定结构；也不要求同时生成短笔记和主题文章、保存两份副本或建立两套目录。已有笔记继续保留。

LoreHub 将 Cubox CLI、Soota、幕布 CLI 和各自的 Skill 一起交付。三个组件来自本仓库维护的版本；修改、构建和安装都以本仓库及 `components.lock.json` 为准。每个 CLI 仍可单独调用，也能导出为独立源码目录。

## 安装

目前提供 macOS Apple Silicon 构建。下载并解压完整发行包后执行：

```sh
./install.sh --prefix "$HOME/.local/share/lorehub" \
  --skills-dir "$HOME/.agents/skills"
export PATH="$HOME/.local/share/lorehub/bin:$PATH"
lorehub doctor
```

安装器一起安装产品命令、三个 CLI 和四个 Skill；遇到已有的非 LoreHub Skill 会停止，保护原安装。可以先省略 `--skills-dir`，安装后从 `lorehub skills list` 查看完整 Skill 路径，或改用一个新的项目 Skill 目录。

发行包包含 Cubox 二进制、Python 依赖 wheel 和全部组件源码。首次安装仍可能联网获取 uv 和 Python；账号登录、浏览器桥接及可选媒体工具按实际任务配置。源码安装还需要 Go。详见 [安装、更新与恢复](docs/installation.md)。

## 使用

先为自己的知识库设置明确目的地：

```sh
lorehub init --vault "/path/to/KnowledgeVault" --subdir "知识"
lorehub batch prepare --ids-file /path/to/card-ids.txt
```

接着让支持 Skill 的 Agent 使用 `lorehub` Skill，读取任务的来源快照与交接文件，按知识库规则写成文章。CLI 不自行调用语言模型；Agent 负责阅读、归并、确认来源覆盖与语义审核。普通文章以连贯段落讲清内容，列表用于确实需要并列或列步骤的部分，不自动把每篇文章改成要点清单。

原文缺失时先用 Soota 补抓，再通过 `prepare --source-bundles /path/to/bundles.json` 传入“收藏 ID → 内容包路径”映射。程序会核对来源身份；补抓文件存在不代表原帖已读全。

```sh
lorehub batch submit /path/to/job --file /path/to/review.json
lorehub batch publish /path/to/job
lorehub batch verify /path/to/job
```

默认到此结束，不要求配置或调用幕布。文章提交仍使用 `notes`、`markdown` 字段，默认模板不含大纲；格式见 [审阅 schema](docs/workflow.md#agent-审阅-schema)。

收藏默认保留。只有用户明确选择清理时，才在 `init` 或本次 `batch prepare` 启用 `--delete-verified`。新的 `init` 默认 `--cleanup-after article`：完整来源已覆盖、有价值内容已处理、文章实际写入并回读通过，就足以进入清理候选，无需等待幕布。`lorehub batch cleanup /path/to/job` 仅预览，加 `--execute` 才执行删除；资料不全和 GitHub 项目保留，不清空 Cubox 最近删除。

旧配置缺少 `cleanup_after` 时仍要求文章和幕布均已核对，升级不会扩大原有删除授权。若用户明确改为“文章完成即可清理”，准备新批次时显式传 `--cleanup-after article`。详细兼容行为见 [交付选择与旧任务](docs/workflow.md#交付选择与旧任务)。

## 按需学习与复习

用户明确提出学习或复习需求后，从已经保存的文章发起独立任务：

```sh
lorehub study prepare --article "/path/to/KnowledgeVault/知识/主题.md" \
  --vault "/path/to/KnowledgeVault" --mubu-doc DOCUMENT_ID
```

可重复传入 `--article FILE` 选择多篇文章；`vault`、幕布文档及可选父节点也可复用配置。Agent 阅读选定文章和返回的审核模板，按概念、关系或问题组织学习树。每个节点保留完整含义及直接相关的简短条件、参数，只为真实上下位关系增加子层级，不把一句话机械拆成几个节点。

```sh
lorehub study submit /path/to/study-job --file /path/to/study-review.json
lorehub study publish /path/to/study-job
lorehub study verify /path/to/study-job
lorehub study status /path/to/study-job
```

`study` 只读原文章并核对冻结指纹，不调用 Cubox 或 Soota，不重写或重建原文章，也不删除收藏。即使原收藏已删除，仍可独立运行。它不会自动在文章完成后启动或定时同步，也不建立幕布返回 Obsidian 的索引。字段与恢复约束见 [学习任务](docs/workflow.md#独立学习任务-study)。

若用户明确要求同一批同时交付文章和大纲，可在 `batch prepare` 加 `--with-outline --mubu-doc DOCUMENT_ID`；仅保存了幕布配置不会启用此模式。需要两处均完成后才清理时，加 `--cleanup-after outline`。

来源、审核结果和写入回执保存在用户状态目录，账号配置仍由各组件管理。现有文章内容冲突或幕布目标下已有同名主题时停止该写入，保留人工内容；已有主题合并需另行审阅，当前没有自动更新功能。详细交接格式、状态与恢复方式见 [知识提炼流程](docs/workflow.md)。

## 独立使用和维护

```sh
lorehub tool cubox -- card batch --ids-file /path/to/card-ids.txt
lorehub tool soota -- ingest URL --want context --max-cost 0 --json
lorehub tool mubu -- --help

lorehub components verify
lorehub components export cubox /path/to/new-cubox-checkout
```

安装目录还提供独立的 `cubox-cli`、`soota`、`mubu-cli` 命令。`lorehub tool` 始终使用当前产品版本绑定的入口，不从 PATH 中误选另一份组件。

开发时直接修改 `modules/` 内对应组件及其 Skill，运行组件相关检查，再刷新锁文件、检查整包并构建。独立导出的源码保留原入口、Skill、测试和许可证。导出不会自动同步已有外部仓库。详见 [组件维护](docs/components.md)。

## 验证与构建

```sh
uv run --python 3.12 pytest
PYTHONPATH=src python3 -m lorehub.cli components verify
python3 packaging/build_release.py --output-dir dist
```

本地检查通过只证明源码、入口及测试覆盖的行为；站点账号、来源完整性和云端写入需要各自的实际回读。公开源码及发行包不包含收藏正文、登录信息、私人知识库路径或执行台账。

产品层和 Soota 使用 GPL-3.0-only；Cubox CLI 与幕布 CLI 保留各自 MIT 许可证及声明，见 [第三方声明](NOTICE.md)。
