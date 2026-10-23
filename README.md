# LoreLab

把内容采集与知识记录所需的工具一起安装：Soota 处理网页、媒体、本地资料和 Cubox 来源，Agent 按要求写成知识文章，再交付到 Obsidian 或明确指定的 Markdown 目录。需要学习或复习时，从选定文章制作幕布大纲。

LoreLab 打包本仓库维护的 Soota、Cubox CLI、幕布 CLI 及完整 Skill。内容流程只有一份实现，位于 Soota；LoreLab 负责成套安装、版本绑定、检查和组件维护。每个 CLI 可独立使用、构建与更新，组件源码和 Skill 可完整导出。原作者仓库仅作人工选择补丁的来源。

## 安装

目前提供 macOS Apple Silicon 构建。下载并解压完整发行包后执行：

```sh
./install.sh --prefix "$HOME/.local/share/lorelab" \
  --skills-dir "$HOME/.agents/skills"
export PATH="$HOME/.local/share/lorelab/bin:$PATH"
lorelab doctor
```

安装包含产品入口、三个独立 CLI、四套 Skill（`lorelab`、`soota`、`cubox`、`mubu-integration`）及 `lorehub` 兼容 Skill。遇到已有的非本产品 Skill 会停止，保护原安装；可以省略 `--skills-dir`，再用 `lorelab skills list` 定位随包 Skill，或使用新的项目 Skill 目录。

发行包包含 Cubox 二进制、Python 依赖 wheel 和全部组件源码。首次安装仍可能联网获取 uv 和 Python；账号登录、浏览器桥接及可选媒体工具按任务配置。源码构建还需要 Go。详见[安装、更新与恢复](docs/installation.md)。

## 采集与知识记录

普通采集默认保存未加工的 context，不自动改写或归档。已有 Soota 命令继续使用：

```sh
soota ingest "URL" --want context --max-cost 0 --json
soota ingest /path/to/audio.m4a --want transcript,context --json
```

明确要求整理知识时，设置目的地并选择来源：

```sh
soota knowledge init --vault /path/to/KnowledgeVault --subdir 知识
soota knowledge prepare --ids-file /path/to/card-ids.txt

# 或：整理已有 Soota v2 内容包，清单是包路径的 JSON 字符串数组
soota knowledge prepare --bundles-file /path/to/source-bundles.json
```

`--ids-file` 与 `--bundles-file` 互斥。Cubox 正文缺失时通过 Soota 现有采集能力补抓，使用 `--source-bundles` 提供收藏 ID 到补抓包的映射。内容包输入只读原包，不调用 Cubox 或删除原始媒体。

让 Agent 使用 **Soota Skill**，实际阅读来源、目标目录规则及相关既有知识，填写任务返回的审阅模板。文章可综合多个来源，保留必要的解释、条件和证据；完整以足够理解和使用为准，不强制长文、固定要点数量或双份笔记。CLI 负责状态、指纹、证据及交付核对，不自行调用语言模型。

```sh
soota knowledge submit /path/to/job --file /path/to/review.json
soota knowledge publish /path/to/job
soota knowledge verify /path/to/job
```

默认到文章实际写入并回读后结束，不要求幕布。已有文件内容冲突会停止，保留人工修改；当前不自动合并或更新已有文章。来源完整性仍需 Agent 审阅，非空正文或通过 hash 校验不等于原帖已读全。

收藏默认保留。适用的明确授权下，Cubox 批次才可启用 `--delete-verified`，核对完成后先用 `soota knowledge cleanup JOB` 预览，再加 `--execute` 执行。资料不全和 GitHub 项目保留；内容包批次始终不删除源文件或收藏。旧配置和旧任务保留原有清理门槛，不随升级扩大授权。字段与完整边界见 [Soota 知识流程](modules/soota/docs/knowledge.md)。

## 按需学习

用户明确要求学习或复习时，从已保存的文章另开任务：

```sh
soota study prepare --article /path/to/KnowledgeVault/知识/主题.md \
  --vault /path/to/KnowledgeVault --mubu-doc DOCUMENT_ID
soota study submit /path/to/study-job --file /path/to/study-review.json
soota study publish /path/to/study-job
soota study verify /path/to/study-job
```

学习树按概念、关系和问题组织，节点保留完整意思，只为真实关系增加层级，不把一句话切成多个碎片。`study` 只读选定文章，不重抓来源、不重写文章或清理收藏；原收藏已删除也可使用。文章完成不会自动启动学习任务或安排同步，也不建立幕布返回 Obsidian 的索引。

明确要求同批交付文章和大纲时，才在 `knowledge prepare` 加 `--with-outline`。流程、审阅模板与恢复约束统一维护在 [Soota 知识流程](modules/soota/docs/knowledge.md)，写作取舍见 [Soota 提示词](modules/soota/skills/soota/references/prompts.md)。

## 兼容与独立维护

`lorelab init/batch/study` 是上述 Soota 命令的薄路由，旧 `lorehub init/batch/study` 继续可用。已有冻结任务按原绝对路径恢复，旧配置原位沿用；安装升级可以继续使用原 LoreHub prefix，无需搬动历史 release。配置优先级见 [Soota 配置与兼容入口](modules/soota/docs/knowledge.md#配置独立组件与兼容入口)。

```sh
lorelab tool cubox -- card batch --ids-file /path/to/card-ids.txt
lorelab tool soota -- knowledge status /path/to/job
lorelab tool mubu -- --agent --help
lorelab components verify
lorelab components export soota /path/to/new-soota-checkout
```

`lorelab tool` 使用当前产品版本绑定的入口，不从 PATH 误选另一份组件。独立导出的 Soota 包含知识流程及完整 Skill 引用，不依赖 LoreLab 或 LoreHub Python 包；Cubox 和幕布按需要使用各自 CLI。开发时直接修改 `modules/` 内对应组件及 Skill，完成检查后刷新组件锁、重建并安装。导出不自动同步外部仓库。详见[组件维护](docs/components.md)。

## 验证与构建

```sh
uv run --python 3.12 pytest
uv run python -m lorelab.cli components verify
python3 packaging/build_release.py --output-dir dist
```

本地检查不代表真实账号、站点或云端交付已验收。公开源码及发行包不包含收藏正文、登录信息、私人知识库路径或执行台账。

产品层和 Soota 使用 GPL-3.0-only；Cubox CLI 与幕布 CLI 保留各自 MIT 许可证及声明，见[组件与许可证](NOTICE.md)。
