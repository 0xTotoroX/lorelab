# lorehub/

> L2 | 父级: ../../AGENTS.md

- `__init__.py`：产品版本。
- `cli.py`：统一命令、用户配置与流程路由。
- `runtime.py`：受管组件绝对路径、版本绑定与 JSON 进程调用。
- `components.py`：组件及 Skill 指纹、来源记录与独立源码导出。
- `workflow.py`：批次准备、提交、发布、核验、清理和状态入口。
- `workflow_state.py`：私有状态、文件锁、路径及不可变文件校验。
- `workflow_sources.py`：Cubox 快照、保护范围、补抓包和 Soota 交接。
- `workflow_review.py`：审阅与独立证据映射、Soota 接续及定稿冻结。
- `workflow_publish.py`：知识文件写入、幕布追加和全树回读。
- `workflow_cleanup.py`：删除预览、一次删除意图及活动/归档回查。

产品层不实现站点私有 API，也不自行生成语义内容。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
