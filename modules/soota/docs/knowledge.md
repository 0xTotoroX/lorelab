# 知识流程迁移到 LoreLab

Soota 负责内容采集、下载、解析、context 和采集任务恢复。跨来源文章、学习大纲、交付回读及收藏清理由 LoreLab 和 LoreLab Skill 负责，Soota 的独立安装不包含这些工作流。

安装 LoreLab 后，使用 `lorelab knowledge` 整理文章、`lorelab study` 制作学习大纲。流程、审阅模板和提示词从 `lorelab skills list` 返回的 LoreLab Skill 进入，不在此复制。

## 配置、独立组件与兼容入口

旧 `soota knowledge/study` 仅转发命令，需要同一 Python 环境中的 LoreLab，或独立安装后可找到的 `lorelab`。受管安装缺失产品入口时停止，不从 PATH 换用另一份产品。普通 Soota 采集不要求安装 LoreLab。

已有知识任务按原 JOB 路径交给 LoreLab，来源、冻结状态和删除条件保持不变。旧配置和显式 `SOOTA_KNOWLEDGE_*` 变量由 LoreLab 兼容读取；不搬动任务或复制私人配置。`soota ingest/jobs/render` 和已有采集任务保持可用，`lorehub` 命令不再提供。
