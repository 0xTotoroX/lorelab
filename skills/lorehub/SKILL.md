---
name: lorehub
description: 用 LoreHub 将 Cubox 收藏或已提供的资料提炼为有来源的知识正文，并按需交付幕布大纲。适用于跨组件知识流程、批次恢复及组件维护；单独的收藏管理、采集或幕布编辑按需读取对应组件 Skill。
---

# LoreHub

LoreHub 将自有 Cubox、Soota、幕布 CLI 与 Skill 组合为一个产品。已有 Agent 负责理解、提炼和审核，CLI 负责确定性读取、采集、状态、写入和核对；无需为此另建 LLM 服务。使用 `lorehub`，先运行 `lorehub doctor` 核对固定 runtime 所绑定的 CLI 与四个 Skill，再用 `lorehub skills list` 定位各 Skill 的 source 入口。不能把系统 PATH 上同名命令当成已验证的产品组件。

## 选择入口

跨工具提炼、保存和恢复先读[统一流程](references/process.md)。正文与大纲的写作取舍见[通用提炼提示](references/prompts.md)。输入、输出、提交文件和状态的完整契约只以 [workflow 文档](../../docs/workflow.md)及当前命令帮助为准，不自行补造字段。

独立操作按需读取相应 source 中的 Skill，不一次加载全部组件文档：

| 任务 | 仓库内 Skill | managed 命令前缀 |
| --- | --- | --- |
| 收藏查询、正文读取、卡片管理 | [Cubox](../../modules/cubox-cli/skills/cubox/SKILL.md) | `lorehub tool cubox -- ORIGINAL_ARGS` |
| 正文、字幕、音频采集与已有任务恢复 | [Soota](../../modules/soota/skills/soota/SKILL.md) | `lorehub tool soota -- ORIGINAL_ARGS` |
| 幕布文档、节点及媒体操作 | [幕布](../../modules/mubu-cli/SKILL.md) | `lorehub tool mubu -- ORIGINAL_ARGS` |

`ORIGINAL_ARGS` 替换为组件原参数，不重复附上原可执行文件。幕布 Agent 调用仍需传入 `--agent`；例如 `lorehub tool mubu -- --agent --auth desktop nodes DOC_ID`。组件 Skill 保持独立可用；跨工具批次的提交、发布和清理由 `lorehub batch` 管理，不能绕过其状态检查直接调用底层写命令。

## 目标与证据

在读写用户选定的知识库前，读取目标目录适用的 `AGENTS.md`，再按需读取其中引用的规则和 prompt。沿用用户指定位置、分类和人工修改保护；缺少影响写入的目标信息时先补齐，不推断私人路径或幕布 ID。个人规则只在用户配置和目标资料库维护，还要核对这些目录自身的 Git、同步及分享边界。

先检查来源是否完整，保留原始正文、链接、来源身份和可核对证据，再按主题提炼正文。正文定稿后才从其实际结构生成大纲，主题、分支与要点数量由内容决定，不固定三条。标题、摘要、非空 `content`、已下载文件均不能单独证明来源完整。

默认保留收藏；来源不完整、证据缺失或核对未完成时保留并说明缺口。GitHub 项目属于受保护来源，不纳入批次清理。清理必须有当前用户针对本批次的明确授权，并且只作用于通过流程核对的项目；已有同一范围的授权无需重复索要。

## 安装与维护

安装目的地允许由用户通过安装器的 `--skills-dir` 指定，不假设某个 Agent 的固定目录。保留 Skill 的引用闭包；仅复制一个 `SKILL.md` 会丢失流程、组件或 schema 文档。安装后从 `lorehub skills list` 返回的 source 读取文件，必要时解析入口符号链接回真实位置。只有入口可发现不代表 Agent 已重新加载最新内容。

组件维护使用 `lorehub components verify`、`lorehub components refresh` 和 `lorehub components export`，参数以当前 `--help` 为准。读[组件维护说明](../../docs/components.md)了解指纹、来源 revision 和独立导出。CLI 与 Skill 从同一份自有源码更新；不切换到原作者发行包，不自动合并上游或推送远端。
