---
name: lorelab
description: 将 Cubox 收藏或已有内容包整理为知识文章，按需从选定文章制作学习大纲，并管理审阅、交付核对、恢复与授权清理。也用于安装、检查和维护 LoreLab 绑定的 CLI 与四套 Skill。单纯采集、下载和解析交给 Soota。
---

# LoreLab

LoreLab 负责跨来源文章、学习大纲和交付流程，打包自行维护的 Soota、Cubox CLI、幕布 CLI 及完整 Skill。Soota 获取源文本、媒体和 context；Agent 实读来源、理解与写作；LoreLab 冻结审阅、核对交付和恢复状态。CLI 不自行调用语言模型。

运行 `lorelab doctor` 核对绑定入口，用 `lorelab skills list` 定位实际 Skill source。入口存在不代表账号、来源完整性或云端交付已通过验收，也不代表 Agent 已重新加载 Skill。

## 选择流程

按实际请求只读相关引用，不默认走完整条链：

| 请求 | 入口与规则 |
| --- | --- |
| 获取正文、下载媒体、字幕或转写 | [Soota Skill](../../modules/soota/skills/soota/SKILL.md)，受管入口 `lorelab tool soota -- ORIGINAL_ARGS` |
| 整理多源文章、知识归档或恢复交付 | [文章与交付流程](references/process.md)、相关[写作提示](references/prompts.md)；正式命令 `lorelab knowledge` |
| 已有文章的学习或复习大纲 | [按需学习任务](references/process.md#按需学习任务)，正式命令 `lorelab study` |
| 粘贴文本作为来源、接入已有内容包 | [来源准备](references/knowledge.md)，保留来源身份，不能把粘贴正文当成 URL 清单 |
| 直接查询或管理收藏 | [Cubox Skill](../../modules/cubox-cli/skills/cubox/SKILL.md)，`lorelab tool cubox -- ORIGINAL_ARGS` |
| 直接编辑幕布文档、节点与媒体 | [幕布 Skill](../../modules/mubu-cli/SKILL.md)，`lorelab tool mubu -- ORIGINAL_ARGS` |

`ORIGINAL_ARGS` 不重复附上可执行文件；幕布 Agent 调用仍须带 `--agent`。恢复 LoreLab 工作流时使用其任务接口，不绕过冻结状态直接重发底层写入或删除。

## 内容与交付

普通采集默认停在 context；总结或分析可直接使用 context，不先增加文章步骤。明确要求知识整理时才选定目的地、阅读目标目录的 `AGENTS.md` 与相关既有笔记。个人分类、prompt 和路径由目标目录或用户配置提供，不放进共享 Skill。

用 `lorelab knowledge prepare --ids-file FILE` 接入明确选定的 Cubox ID，或用互斥的 `--bundles-file FILE` 接入 Soota v2 内容包。以返回的真实 JOB、来源、指纹和审阅模板为准。Agent 必须实读并判断来源完整性；程序校验不能证明语义覆盖。

文章写成连贯、足够理解和使用的内容，可综合多个来源，不强制长度、要点数量或双份笔记。默认到文章写入并回读结束。只有明确学习请求才从选定文章启动 `lorelab study`；同批文章和大纲须显式 `--with-outline`。学习节点保留完整意思，层级反映真实关系，不拆碎句，不建立幕布回写 Obsidian 的索引。

默认保留收藏；仅适用的明确授权、完整来源覆盖和所选交付回读均满足后，才经 `knowledge cleanup` 预览和执行。资料不全与 GitHub 项目保留，内容包来源和 study 不清理原始资料。一次派发结果不确定时只读对账，不重新导入或删除。具体字段、门槛和恢复以 [工作流契约](../../docs/knowledge.md) 为准。

## 旧命令与任务

`lorelab knowledge/study` 是正式入口，`lorelab init/batch` 保留为产品别名。旧 `soota knowledge/study` 仅转发原参数，需要已安装 LoreLab；独立 Soota 不再包含工作流实现。旧 `lorehub` 命令、Python 入口和 Skill 继续保持移除。

旧 JOB 按原绝对路径继续，冻结 schema、来源指纹和原清理条件不变。配置路径、旧环境变量和共享写锁见[兼容说明](../../docs/knowledge.md#配置独立组件与兼容入口)。不复制私人配置、不搬动任务目录或更改历史授权。

## 安装与组件维护

阅读[安装与恢复](../../docs/installation.md)或[组件维护](../../docs/components.md)，只执行当前请求需要的操作。`sh install.sh` 默认一起安装四个 CLI、注册四套 Skill；`setup` 配置知识目的地和命令路径，显式参数只合并对应字段。Agent 使用 `--non-interactive`，已有配置无须重填；检查账号须显式 `--check-accounts`。

升级使用 `lorelab update --from FILE`，或事先通过 `setup --update-feed` 配置发布者清单；没有配置时不猜下载地址。相同包复用现有安装，更新保留注册目录、任务和清理条件。新目录可用 `--skills-dir` / `--bin-dir` 指定，外部同名内容不覆盖。

作为[四 Skill 插件](../../docs/plugins.md)加载时，先按插件内 RUNTIME 约定检查 `doctor --plugin-root`，CLI 与插件须同版。插件已提供 Skill 时安装和 setup 带 `--no-skills`，避免新增重复注册；不主动删除已有 Skill。当前运行环境仅 macOS arm64，不把安卓远程操作写成手机本机支持。

安装或维护授权不额外授权语义改写、知识库写入、云端发布或删除来源。

组件源码和对应 Skill 在 `modules/` 内维护；工作流源码在 `src/lorelab/knowledge/`，流程和提示词在本 Skill 中维护。审阅改动并完成验证后刷新组件锁，再重建受管 runtime。`components export` 导出独立组件及其 Skill，不携带 LoreLab 工作流、不自动同步外部仓库或切换原作者版本。

个人账号、凭据、资料和执行记录留在用户配置、状态目录或指定知识库中，核对其 Git 与同步边界。历史安装 prefix 包含绝对路径，升级原位切换，不为改名搬动安装目录。
