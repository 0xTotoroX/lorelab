---
name: lorehub
description: 用 LoreHub 将 Cubox 收藏整理成有来源的完整文章，保存到明确知识目的地后结束；用户另行要求学习或复习时，从选定文章制作幕布大纲。也用于批次恢复及组件维护；单独的收藏管理、采集或幕布编辑使用对应组件 Skill。
---

# LoreHub

LoreHub 将自有 Cubox、Soota、幕布 CLI 与 Skill 组合为一个产品。已有 Agent 负责理解、提炼和审核，CLI 负责确定性读取、采集、状态、写入和核对；无需为此另建 LLM 服务。使用 `lorehub`，先运行 `lorehub doctor` 核对固定 runtime 所绑定的 CLI 与四个 Skill，再用 `lorehub skills list` 定位各 Skill 的 source 入口。不能把系统 PATH 上同名命令当成已验证的产品组件。

## 选择入口

收藏到文章的提炼、保存和恢复先读[文章流程](references/process.md#文章任务)。用户明确要求学习或复习已存文章时，读[学习任务](references/process.md#按需学习任务)。文章与学习树的写作取舍见[通用提炼提示](references/prompts.md)。输入、输出、提交文件和状态的完整契约只以 [workflow 文档](../../docs/workflow.md)及当前命令帮助为准，不自行补造字段。

默认 `lorehub batch` 在文章写入并回读后结束，不要求幕布目标。`lorehub study` 是用户选定已有文章后另行发起的任务，不依赖原收藏是否已删除，不调用 Cubox/Soota，不改写文章或清理收藏。只有用户明确要求同批交付文章和大纲时才传 `batch prepare --with-outline`；已有幕布配置不构成这一请求。不自动建立文章到幕布的定时同步，也不添加返回 Obsidian 的索引。

独立操作按需读取相应 source 中的 Skill，不一次加载全部组件文档：

| 任务 | 仓库内 Skill | managed 命令前缀 |
| --- | --- | --- |
| 收藏查询、正文读取、卡片管理 | [Cubox](../../modules/cubox-cli/skills/cubox/SKILL.md) | `lorehub tool cubox -- ORIGINAL_ARGS` |
| 正文、字幕、音频采集与已有任务恢复 | [Soota](../../modules/soota/skills/soota/SKILL.md) | `lorehub tool soota -- ORIGINAL_ARGS` |
| 幕布文档、节点及媒体操作 | [幕布](../../modules/mubu-cli/SKILL.md) | `lorehub tool mubu -- ORIGINAL_ARGS` |

`ORIGINAL_ARGS` 替换为组件原参数，不重复附上原可执行文件。幕布 Agent 调用仍需传入 `--agent`；例如 `lorehub tool mubu -- --agent --auth desktop nodes DOC_ID`。组件 Skill 保持独立可用；文章批次由 `lorehub batch` 管理，独立学习任务由 `lorehub study` 管理，不能绕过任务状态检查直接调用底层写命令。

## 目标与证据

在读写用户选定的知识库前，读取目标目录适用的 `AGENTS.md`，再按需读取其中引用的规则和 prompt。沿用用户指定位置、分类和人工修改保护；文章任务只需明确知识目的地，学习任务再核对所选文章与幕布目标。已有授权配置可直接复用，不推断私人路径或幕布 ID。个人规则只在用户配置和目标资料库维护，还要核对这些目录自身的 Git、同步及分享边界。

先检查来源是否完整，保留原始正文、链接、来源身份和可核对证据，再写成可独立阅读的连贯文章。一篇可综合多个来源，讲清关系和条件；完整以内容足够为准，不等于长篇、修辞堆砌或强制作文。不要求短笔记与主题文章双份归档、两套目录，也不把每篇文章自动改成列表。已有笔记保留；冲突交由独立审阅，当前没有自动合并或更新功能。标题、摘要、非空 `content`、已下载文件均不能单独证明来源完整。

学习树只从已定稿文章组织概念、关系或问题，保留实用条件与例外。每个节点是完整可理解的知识单元，可合放直接相关的简短条件和参数；子层级只表达真实上下位关系，不要求一叶一操作或判断。简单观点完整保留，不把一句话拆成几个节点，不固定层级、分支或要点数量；容量上限不是写作配额。

默认保留收藏。用户选择启用删除且 `cleanup_after=article` 时，完整来源覆盖、有价值内容已处理、文章实际写入并回读通过足以进入清理候选，无需幕布。来源不完整、证据缺失、冲突或核对未完成时保留并说明缺口；GitHub 项目受保护。清理仅作用于适用授权范围内通过程序核对的项目，同一范围的明确授权无需重复索要。旧任务和旧配置缺少新字段时仍保留原有两处核对门槛，不能把旧删除授权静默扩大。

## 安装与维护

安装目的地允许由用户通过安装器的 `--skills-dir` 指定，不假设某个 Agent 的固定目录。保留 Skill 的引用闭包；仅复制一个 `SKILL.md` 会丢失流程、组件或 schema 文档。安装后从 `lorehub skills list` 返回的 source 读取文件，必要时解析入口符号链接回真实位置。只有入口可发现不代表 Agent 已重新加载最新内容。

组件维护使用 `lorehub components verify`、`lorehub components refresh` 和 `lorehub components export`，参数以当前 `--help` 为准。读[组件维护说明](../../docs/components.md)了解指纹、来源 revision 和独立导出。CLI 与 Skill 从同一份自有源码更新；不切换到原作者发行包，不自动合并上游或推送远端。
