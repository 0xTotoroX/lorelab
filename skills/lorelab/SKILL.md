---
name: lorelab
description: 安装、检查和维护 LoreLab 成套内容工具，定位绑定的 CLI 与 Skill、导出独立组件。内容采集、文章整理、学习大纲及交付恢复路由到 Soota；收藏管理和幕布编辑使用各自组件 Skill。
---

# LoreLab

LoreLab 打包自有 Soota、Cubox CLI、幕布 CLI 及完整 Skill。它负责安装、版本绑定、组件维护和入口路由；内容流程仅在 Soota 实现。已有 Agent 负责理解与写作，无需另建 LLM 服务。

运行 `lorelab doctor` 核对绑定入口，用 `lorelab skills list` 定位实际 Skill source。不能把 PATH 上同名命令当作已验证组件。只有入口存在不代表账号或云端写入已验证，也不代表 Agent 已重新加载 Skill。

## 路由

按实际请求只读相应 Skill，不一次加载全部文档：

| 任务 | Skill | 受管命令前缀 |
| --- | --- | --- |
| 采集、文章整理、知识交付、学习大纲与任务恢复 | [Soota](../../modules/soota/skills/soota/SKILL.md) | `lorelab tool soota -- ORIGINAL_ARGS` |
| 收藏查询、正文读取与卡片管理 | [Cubox](../../modules/cubox-cli/skills/cubox/SKILL.md) | `lorelab tool cubox -- ORIGINAL_ARGS` |
| 独立幕布文档、节点与媒体操作 | [幕布](../../modules/mubu-cli/SKILL.md) | `lorelab tool mubu -- ORIGINAL_ARGS` |

`ORIGINAL_ARGS` 不重复附上可执行文件，幕布 Agent 调用仍须带 `--agent`。正在恢复的知识或学习任务继续走 Soota 的任务接口，不绕过其冻结和写入检查直接重发底层命令。

`lorelab init/batch/study` 分别路由到 `soota knowledge init`、`soota knowledge`、`soota study`。旧 `lorehub` 命令、Python 兼容入口和 Skill 已移除；恢复旧任务时把原 JOB 路径交给上述现行入口。字段、默认行为、旧配置与任务兼容只查 [Soota 知识契约](../../modules/soota/docs/knowledge.md)及当前帮助，本 Skill 不复制流程或提示词。

## 安装与组件维护

阅读[安装与恢复](../../docs/installation.md)或[组件维护](../../docs/components.md)，只执行当前请求需要的操作。产品分发四个 CLI（`lorelab`、`soota`、`cubox-cli`、`mubu-cli`）和四套 Skill（`lorelab`、`soota`、`cubox`、`mubu-integration`）。Skills 注册目录由安装器 `--skills-dir` 指定；保留整个 Skill 及相对引用闭包，不能只复制孤立的 SKILL.md。旧 prefix 可以继续升级，安装器清理它拥有的旧命令与 Skill 链接，历史 release 留作备份；不移动含绝对路径的安装目录，也不为名称统一改写旧配置或锁目录。

组件源码和对应 Skill 在 `modules/` 内一起维护。使用 `lorelab components verify` 检查内容指纹；审阅本轮变化并完成相关验证后才 `refresh`，再重建受管 runtime。`components export` 导出自含源码和 Skill，不自动同步其他仓库。CLI 和 Skill 不切换到原作者发行包，不自动合并上游或推送。

个人路径、账号、凭据、资料、处理记录和规则留在用户配置或目的地中；配置变更仍须核对其 Git 与同步边界。安装或维护授权不额外授权语义改写、知识库写入、云端发布或删除来源。
