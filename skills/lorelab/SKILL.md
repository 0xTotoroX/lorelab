---
name: lorelab
description: 处理单来源分析、笔记、文章与内容包导出，按目标规则审阅知识分类、查重和合并；整理 Cubox 收藏或内容包、制作按需学习大纲，管理交付、恢复与授权清理。也用于 LoreLab 安装维护。纯采集交给 Soota，普通聊天总结不要求入库。
---

# LoreLab

LoreLab content 负责单来源分析、笔记、文章、大纲与整包导出，knowledge/study 负责知识文章、学习和交付流程，从本仓库安装自行维护的 Soota、Cubox CLI、幕布 CLI 及完整 Skill。Soota 获取源文本、媒体和 context；Agent 实读来源、理解、写作并审阅分类与合并；LoreLab 校验提交、渲染产物、冻结知识审阅、核对交付和恢复状态。CLI 不自行调用语言模型。

运行 `lorelab doctor` 核对绑定入口，用 `lorelab skills list` 定位实际 Skill source。入口存在不代表账号、来源完整性或云端交付已通过验收，也不代表 Agent 已重新加载 Skill。

## 选择流程

按实际请求只读相关引用，不默认走完整条链：

| 请求 | 入口与规则 |
| --- | --- |
| 获取正文、下载媒体、字幕或转写 | [Soota Skill](../../modules/soota/skills/soota/SKILL.md)，受管入口 `lorelab tool soota -- ORIGINAL_ARGS` |
| 单来源分析、笔记、阅读文章或整包导出 | [内容处理](references/content.md)，正式命令 `lorelab content ingest/resume/render/export` |
| 知识分类、查重与既有笔记合并 | [分类与交付](references/content.md#分类查重与交付)，由 Agent 审阅并按授权实施，CLI 不自动合并 |
| 整理多源文章、知识归档或恢复交付 | [文章与交付流程](references/process.md)、相关[写作提示](references/prompts.md)；正式命令 `lorelab knowledge` |
| 已有文章的学习或复习大纲 | [按需学习任务](references/process.md#按需学习任务)，正式命令 `lorelab study` |
| 粘贴文本作为来源、接入已有内容包 | [来源准备](references/knowledge.md)，保留来源身份，不能把粘贴正文当成 URL 清单 |
| 直接查询或管理收藏 | [Cubox Skill](../../modules/cubox-cli/skills/cubox/SKILL.md)，`lorelab tool cubox -- ORIGINAL_ARGS` |
| 直接编辑幕布文档、节点与媒体 | [幕布 Skill](../../modules/mubu-cli/SKILL.md)，`lorelab tool mubu -- ORIGINAL_ARGS` |

`ORIGINAL_ARGS` 不重复附上可执行文件；幕布 Agent 调用仍须带 `--agent`。恢复 LoreLab 工作流时使用其任务接口，不绕过冻结状态直接重发底层写入或删除。

## 内容与交付

普通采集默认停在 context；总结或分析可直接使用 context，不先增加文章步骤。普通聊天总结直接回答，不要求采集、创建任务或入库。需要保存单来源语义产物时使用 `lorelab content`；Soota 新任务只处理 `video/audio/transcript/context/markdown/images/data`。明确要求知识整理时才选定目的地、阅读目标目录的 `AGENTS.md` 与相关既有笔记。个人分类、prompt 和路径由目标目录或用户配置提供，不放进共享 Skill。

用 `lorelab knowledge prepare --ids-file FILE` 接入明确选定的 Cubox ID，或用互斥的 `--bundles-file FILE` 接入 Soota v2 内容包。以返回的真实 JOB、来源、指纹和审阅模板为准。Agent 必须实读并判断来源完整性；程序校验不能证明语义覆盖。

分类、查重和合并既有笔记由 Agent 对照相关内容审阅；按当前授权单独实施合并并回读，保留人工内容。`knowledge publish` 仅写新路径或复用字节相同的文件，不自动覆盖或合并，也不为绕过冲突另存重复主题。

文章写成连贯、足够理解和使用的内容，可综合多个来源，不强制长度、要点数量或双份笔记。默认到文章写入并回读结束。只有明确学习请求才从选定文章启动 `lorelab study`；同批文章和大纲须显式 `--with-outline`。学习节点保留完整意思，层级反映真实关系，不拆碎句，不建立幕布回写 Obsidian 的索引。

默认保留收藏；仅适用的明确授权、完整来源覆盖和所选交付回读均满足后，才经 `knowledge cleanup` 预览和执行。资料不全与 GitHub 项目保留，内容包来源和 study 不清理原始资料。一次派发结果不确定时只读对账，不重新导入或删除。具体字段、门槛和恢复以 [工作流契约](../../docs/knowledge.md) 为准。

## 旧命令与任务

`lorelab content` 是语义内容与导出的正式入口，旧 `soota ingest` 的语义目标/导出参数、旧语义或交付任务的 `soota jobs resume` 和 `soota render` 仅作隐藏兼容转发，动态调用同一 Python 环境的 LoreLab，不从 PATH 另选产品。未安装 LoreLab 时明确报需要安装，在修改任务、预算或产物前停止；采集与原文包不依赖 LoreLab。详情见[内容兼容契约](../../docs/content.md#旧入口与恢复)。

`lorelab knowledge/study` 是知识与学习的正式入口，`lorelab init/batch` 保留为产品别名。旧 `soota knowledge/study` 仅转发原参数，需要已安装 LoreLab；独立 Soota 不再包含工作流实现。旧 `lorehub` 命令、Python 入口和 Skill 继续保持移除。

旧 JOB 按原 ID/绝对路径继续，task/item 身份、source 证据、预算、产物及冻结 schema、来源指纹和原清理条件不变。配置路径、旧环境变量和共享写锁见[兼容说明](../../docs/knowledge.md#配置独立组件与兼容入口)。不复制私人配置、不搬动任务目录或更改历史授权。

## 安装与组件维护

首次安装和源码更新先读[Agent 安装指引](../../docs/agent-install.md)，详细参数见[安装与恢复](../../docs/installation.md)。使用用户提供的实际仓库地址；本地 Agent 按 macOS 或 Linux `install.sh` / Windows `install.ps1` 选择入口，自动准备缺失工具链并从绑定源码安装四个 CLI 和四套 Skill，不要求下载 LoreLab 安装包。

`setup --non-interactive` 保留已有配置，只合并显式目的地；不猜知识库路径，检查账号须显式 `--check-accounts`。同名外部内容不覆盖，沿用已有 prefix 和任务。普通更新用 `lorelab update --check`、`lorelab update`；从指定源码更新用 `--from CHECKOUT`，或 `--repo REPOSITORY --ref REF`。来源由安装记录保存，更新使用独立快照，不修改用户工作区；相同内容校验后复用，不重复构建。

作为[四 Skill 插件](../../docs/plugins.md)加载时，先按 RUNTIME 检查 `doctor --plugin-root`。插件只分发四套独立 Skill、文档和安装指引，没有 CLI 或运行安装包。缺少 CLI 时由本地 Agent 从用户选择的仓库安装，安装和 setup 带 `--no-skills`，避免重复全局注册。CLI 与插件源码版本需匹配；不修改宿主缓存，不把静态检查或其他平台验证写成 Windows 实机验收。

安装或维护授权不额外授权语义改写、知识库写入、云端发布或删除来源。

组件源码和对应 Skill 在 `modules/` 内维护；语义校验、渲染与导出源码在 `src/lorelab/content/`，知识与学习工作流在 `src/lorelab/knowledge/`；流程和提示词在本 Skill 中维护。三个组件的唯一修改入口是对应 `modules/cubox-cli/`、`modules/soota/`、`modules/mubu-cli/`，独立仓库由单向同步生成；开发、同步或发布时读[同步与发布](../../docs/releases.md)。审阅验证后刷新组件锁并提交，`components sync NAME --source CHECKOUT`（NAME 为 cubox、soota 或 mubu） 默认预览，`--execute` 才推送；`release prepare/publish` 仍只联动 LoreLab 与 Soota 两包版本和标签。独立修改、过期源或标签冲突先停止核对，不强推、不改回执跳过校验。`components export` 仍只导出完整源码及 Skill，不自行推送。同步/发布授权与用户内容交付授权分别核对；版本就绪不代表云端工作流已启用。

维护开发仓库时，`components verify/refresh/export` 显式带 `--source CHECKOUT`；省略时使用当前绑定源码，不能把已安装的快照当作开发主源。

个人账号、凭据、资料和执行记录留在用户配置、状态目录或指定知识库中，核对其 Git 与同步边界。历史安装 prefix 包含绝对路径，升级原位切换，不为改名搬动安装目录。
