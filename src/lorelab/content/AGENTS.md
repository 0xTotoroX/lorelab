# content/

> L2 | 父级：[项目约定](../../../AGENTS.md)

单份或批量来源的分析、笔记、文章和内容包交付。Agent 负责理解与写作，CLI 负责身份、来源指纹、证据及落盘核验。知识分类与文章交付由 LoreLab Skill 和相邻 `knowledge/` 统一组织。Soota 是单向采集依赖；此模块不复制 Provider 或下载实现。

- `__init__.py`：包入口。
- `api.py`：请求目标解析与内容任务入口；复用 Soota 原始参数验证。
- `cli.py`：`content ingest/resume/render/export`，兼容旧参数。
- `models.py`：语义提交类型、内容任务和纯采集请求投影。
- `tasks.py`：复用 Soota 获取阶段，接续分析与导出，保留任务身份和累计预算。
- `outputs.py`：Agent 交接、身份和指纹校验；旧冻结交接内容不无故重写。
- `analysis.py`：v2 语义产物与证据校验，原文保持不变。
- `render.py`：v1/v2 渲染分流与回执。
- `legacy.py`：旧 v1 `content.md` 写入和原始上下文保全。
- `load_analysis.py`：旧 v1 Analysis JSON 校验。
- `markdown.py`：旧 v1 派生 Markdown 与证据链接。
- `export.py`：显式目的地、冲突预检和兼容旧导出回执。

旧任务仍在其原存储路径中恢复，沿用 job/item 身份、原文指纹、预算和锁；默认不迁移或复制用户数据。完成采集不代表分析或知识交付完成。导出保护不被 render/采集的 `--force` 绕过。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
