# LoreLab

Python 3.12+ 产品层 + Go Cubox CLI + Python Soota / 幕布 CLI。

## 职责与目录

- `modules/`：自有组件源码，各模块保留独立入口、Skill、测试和许可证。组件原有 AGENTS.md 继续适用。
- `src/lorelab/`：产品 CLI、组件定位、安装检查；`knowledge/` 是文章、学习与交付流程的唯一实现。
- `skills/lorelab/`：文章、学习、交付、清理与产品维护。采集规则在 Soota Skill 维护，Cubox/幕布的服务操作约定留在各自 Skill。
- `packaging/`：成套构建、安装与版本校验；只从本仓库构建组件，禁止自动切换到原作者发行包。
- `tests/`：产品安装、版本绑定、旧入口移除及数据兼容测试；知识状态恢复及写入边界测试位于 `tests/knowledge/`。
- `docs/`：已实现使用说明、架构及组件维护方法。

## 约定

本仓库是产品开发主源。`components.lock.json` 记录导入来源提交及当前源码指纹，修改组件或 Skill 时同步刷新并验收。原作者仓库仅为人工选择的补丁来源。独立源码导出与组件命令必须持续可用。

所有个人账号、路径、原始收藏、执行记录与发布草稿保存到用户配置/状态目录，不进入本仓库或发行包。公开文档不写个人计划。流程默认保留收藏；仅按当前用户明确授权执行已核对项目的清理，GitHub 项目保护与资料不全保留由流程校验。

内容理解、全文审阅和语义写作由 Agent 按 LoreLab Skill 完成；LoreLab `knowledge/` 管理来源快照、审阅冻结、交付核对、恢复和授权清理。普通 ingest 默认到原文 context 结束，不擅自改写。显式知识任务默认写成完整、连贯的文章并回读，可综合多个来源，不强制长文或双份归档；明确要求学习时才从选定文章发起独立 study，或显式启用同批大纲。学习节点保留完整含义，不固定分支数量，不建幕布返回 Obsidian 的索引。已有文件冲突需另行审阅，保留人工修改。Cubox 与幕布只通过各自 CLI 操作，不接入服务私有 API。

流程契约主源是 `docs/knowledge.md`，操作与提示词主源是 `skills/lorelab/references/{process,prompts}.md`。Soota 只持有采集、内容包和单项产物契约；独立导出不携带 LoreLab 工作流，普通采集不依赖 LoreLab。分发仅含 `lorelab`、`soota`、`cubox-cli`、`mubu-cli` 四个 CLI 和 `lorelab`、`soota`、`cubox`、`mubu-integration` 四套 Skill。`lorehub` 命令、Python 兼容包及 Skill 已移除。既有知识任务通过 `lorelab knowledge/study` 按原路径继续；旧 `soota knowledge/study` 仅兼容转发，需要 LoreLab，旧配置不静默复制或放宽删除；历史 prefix、配置、环境变量与共享写锁名称保留用于数据兼容，不要求恢复旧入口。内容包来源只读，不调用 Cubox 或删除来源。

测试与构建命令以 README 和 packaging 说明为准。变更结构时更新对应模块地图。实现完成后本地提交，不自动推送或发布。
