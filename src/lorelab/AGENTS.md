# lorelab/

> L2 | 父级: ../../AGENTS.md

- `__init__.py`：统一产品版本。
- `cli.py`：安装检查、组件与 Skill 管理；knowledge/study 以及 init/batch 别名进入产品工作流。
- `runtime.py`：受管组件版本绑定和命令转交；知识配置委派产品 knowledge 模块。
- `components.py`：组件及 Skill 指纹、来源记录与独立源码导出。

- `knowledge/`：跨来源审阅、文章、学习、交付核对与授权清理的唯一实现。

内容流程、证据、任务状态与交付归 `lorelab.knowledge`；采集、解析、context 与采集任务恢复归 Soota。旧知识命令仅转交本产品，已有任务按原路径读取，不保留第二份工作流代码。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
