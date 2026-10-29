# LoreLab

Python 3.12+ 产品层 + Go Cubox CLI + Python Soota / 幕布 CLI + React / TypeScript 配置台。

## 职责与目录

- `modules/`：自有组件源码，各模块保留独立入口、Skill、测试和许可证。组件原有 AGENTS.md 继续适用。
- `src/lorelab/`：产品 CLI、组件定位、安装检查；`content/` 唯一实现语义目标、分析提交校验、渲染与整包导出，复用 Soota 采集；`knowledge/` 管理文章、学习与交付，内部语义操作调用 `content/`。
- `web/`：配置台 GUI 源码；Obsidian 灰紫深浅主题、完整侧栏、三列分组、流光与诊断。当前使用内存示例数据，未接真实 CLI / HTTP / 配置文件；运行与验证见 `web/README.md`。
- `skills/lorelab/`：单来源分析、笔记、文章、分类审阅、学习、交付、清理与产品维护。采集规则在 Soota Skill 维护，Cubox/幕布的服务操作约定留在各自 Skill。
- `packaging/`：本地 Agent 源码安装、跨平台工具链、注册事务与纯 Skill 插件打包；只从本仓库构建组件，禁止自动切换到原作者发行包。
- `tests/`：产品安装、版本绑定、旧入口移除及数据兼容测试；知识状态恢复及写入边界测试位于 `tests/knowledge/`。
- `docs/`：已实现使用说明、架构及组件维护方法。

## 约定

本仓库是产品开发主源。`components.lock.json` 记录导入来源提交及当前源码指纹，修改组件或 Skill 时同步刷新并验收。原作者仓库仅为人工选择的补丁来源。独立源码导出与组件命令必须持续可用。

Cubox、Soota、幕布的源码、测试、文档与 Skill 只修改对应 `modules/cubox-cli/`、`modules/soota/`、`modules/mubu-cli/`。三个独立仓库都是单向生成的发行出口；`components sync {cubox,soota,mubu}` 从已提交、指纹一致的主源生成后继提交，保留原历史，拒绝独立修改、倒退与强推。`release prepare/publish` 统一准备两包版本和配对标签，GitHub 工作流分发源码与纯 Skill 插件；具体契约见 `docs/releases.md`。首次历史接入只保留原提交图，不以旧根目录覆盖产品源码。

所有个人账号、路径、原始收藏、执行记录与发布草稿保存到用户配置/状态目录，不进入本仓库或发行包。公开文档不写个人计划。流程默认保留收藏；仅按当前用户明确授权执行已核对项目的清理，GitHub 项目保护与资料不全保留由流程校验。

内容理解、全文审阅、语义写作与分类查重合并由 Agent 按 LoreLab Skill 完成；CLI 不调用模型、不推断分类。LoreLab `content/` 校验并保存 Agent 提交、渲染与导出；`knowledge/` 管理来源快照、审阅冻结、交付核对、恢复和授权清理。普通 ingest 默认到原文 context 结束，不擅自改写。显式知识任务默认写成完整、连贯的文章并回读，可综合多个来源，不强制长文或双份归档；明确要求学习时才从选定文章发起独立 study，或显式启用同批大纲。学习节点保留完整含义，不固定分支数量，不建幕布返回 Obsidian 的索引。已有文件冲突由 Agent 在当前授权内另行审阅合并并回读，保留人工修改。`knowledge publish` 只写新路径或复用相同 bytes，不能宣称自动覆盖、合并或更新已有笔记。普通聊天总结不要求入库，不强加文章前置或三点格式。Cubox 与幕布只通过各自 CLI 操作，不接入服务私有 API。

内容契约主源是 `docs/content.md`，知识与学习流程主源是 `docs/knowledge.md`；操作与语义指导在 `skills/lorelab/references/{content,process,prompts}.md` 维护。Soota 新任务只接受 `video/audio/transcript/context/markdown/images/data`；`note/article/analysis/outline` 及 `--destination/--vault/--subdir` 的实现全部归 LoreLab content。采集与原文包独立不依赖 LoreLab；`Analysis`、`KeyPoint`、`Chapter` 与所有语义渲染实现归 `src/lorelab/content/`，分析 schema 位于主仓 `schemas/analysis.v1.json`。Soota 的旧 `TaskSpec` 语义词/目标字段和 `AnalysisManifest` 状态只作数据兼容，不据此保留语义执行或导出实现。分发仅含 `lorelab`、`soota`、`cubox-cli`、`mubu-cli` 四个 CLI 和 `lorelab`、`soota`、`cubox`、`mubu-integration` 四套 Skill。`lorehub` 命令、Python 兼容包及 Skill 已移除。既有知识任务通过 `lorelab knowledge/study` 按原路径继续；旧 `soota knowledge/study` 仅兼容转发；旧 `soota ingest` 的语义目标/导出参数、旧语义或交付任务的 `soota jobs resume`、`soota render` 仅作隐藏桥，动态调用同一 Python 环境的 LoreLab content，不从 PATH 另选产品。未安装 LoreLab 时明确报需要安装，在修改任务、预算或产物前停止。原 task/item 身份、source 证据、路径、费用预留与产物保持；交接身份、指纹、目标不变时保留 `analysis-request.json` 原字节和冻结 hash，旧配置不静默复制或放宽删除；历史 prefix、配置、环境变量与共享写锁名称保留用于数据兼容，不要求恢复旧入口。内容包来源只读，不调用 Cubox 或删除来源。

测试与构建命令以 README 和 packaging 说明为准。变更结构时更新对应模块地图。实现完成后本地提交，不自动推送或发布。

GUI 的开发主源为 `web/`，只维护已确认的后台配置与运行管理界面，不恢复旧阅读稿或历史布局选择器。前端使用自己的 npm lockfile；Node 与前端产物不加入现有 CLI / Skill 安装链路。真实后端接入前必须按现有 CLI 和配置契约逐项映射，不把示例端点、预算或任务字段当成真实接口。

安装以用户提供的仓库为入口，macOS / Linux / Windows 在本机从锁定源码构建，不要求维护者提供安装包。插件仅含四套独立 Skill、引用文档与安装指引；不要重新内置 CLI、依赖或运行包。源码更新使用独立 Git 快照，保留开发 checkout、旧 release、配置和任务。平台验收必须区分实际机器、交叉编译与模拟测试。
