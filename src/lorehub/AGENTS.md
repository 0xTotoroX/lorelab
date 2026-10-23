# lorehub/

> L2 | 父级: ../../AGENTS.md

- `__init__.py`：产品版本。
- `cli.py`：统一命令、用户配置、文章批次及按需学习任务路由。
- `runtime.py`：受管组件绝对路径、版本绑定与 JSON 进程调用。
- `components.py`：组件及 Skill 指纹、来源记录与独立源码导出。
- `workflow.py`：默认文章交付、显式组合交付及批次清理入口。
- `study.py`：显式文章快照、学习大纲提交与独立幕布交付，不改写文章或读删收藏。
- `workflow_state.py`：私有状态、文件锁、路径、不可变文件校验及旧批次交付契约兼容。
- `workflow_sources.py`：Cubox 快照、保护范围、补抓包和 Soota 交接。
- `workflow_review.py`：按实际目标审阅与独立证据映射、Soota 接续及定稿冻结。
- `workflow_publish.py`：独立文章写入/核对，可复用的幕布单次追加和全树回读。
- `workflow_cleanup.py`：依据已授权完成条件删除预览、一次删除意图及活动/归档回查。

产品层不实现站点私有 API，也不自行生成语义内容。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
