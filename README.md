# LoreHub

把收藏变成可以查用的知识：Cubox 保存输入，Obsidian 保存正文，幕布保存便于记忆的大纲。

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
lorehub init --vault "/path/to/ObsidianVault" --subdir "知识" \
  --mubu-doc DOCUMENT_ID --mubu-parent PARENT_NODE_ID
lorehub batch prepare --ids-file /path/to/card-ids.txt
```

接着让支持 Skill 的 Agent 使用 `lorehub` Skill，读取任务的来源快照与交接文件，按知识库规则整理内容。CLI 不自行调用语言模型；Agent 负责阅读、归并、确认来源覆盖，先定稿正文，再按实际结构生成大纲。

原文缺失时先用 Soota 补抓，再通过 `prepare --source-bundles /path/to/bundles.json` 传入“收藏 ID → 内容包路径”映射。程序会核对来源身份；补抓文件存在不代表原帖已读全。

```sh
lorehub batch submit /path/to/job --file /path/to/review.json
lorehub batch publish /path/to/job
lorehub batch verify /path/to/job
lorehub batch cleanup /path/to/job
```

`cleanup` 默认仅预览。只有该批任务已明确启用 `--delete-verified`，且来源覆盖、正文、大纲和回读全部通过，才允许加 `--execute` 删除对应收藏。资料不全的保留，GitHub 项目受保护。不写幕布返回 Obsidian 的索引，不清空 Cubox 最近删除。

来源、审核结果和写入回执保存在用户状态目录，账号配置仍由各组件管理。现有笔记内容冲突时停止该写入，不覆盖人工修改；本版批量发布支持新增笔记和追加幕布子树，已有主题合并由 Agent 审阅后另行处理。详细交接格式、状态与恢复方式见 [知识提炼流程](docs/workflow.md)。

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
