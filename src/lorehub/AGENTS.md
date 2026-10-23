# lorehub/ 兼容入口

> L2 | 父级: ../../AGENTS.md

- `__init__.py`、`cli.py`、`runtime.py`、`components.py`：旧产品导入/命令委派 `lorelab`。
- `workflow.py`、`workflow_sources.py`、`workflow_review.py`、`workflow_publish.py`、`workflow_cleanup.py`、`workflow_state.py`、`study.py`：旧模块名称指向 `soota.knowledge` 的同一模块对象，保留既有 API 与任务行为。

不在兼容层增加业务逻辑、第二份状态或流程提示词。旧冻结任务保留原路径和完成条件。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
