# lorelab/

> L2 | 父级: ../../AGENTS.md

- `__init__.py`：统一产品版本。
- `cli.py`：安装检查、组件与 Skill 管理；init/batch/study 委派 Soota 同一解析与流程。
- `runtime.py`：受管组件版本绑定和命令转交；知识配置委派 Soota。
- `components.py`：组件及 Skill 指纹、来源记录与独立源码导出。

内容流程、证据、任务状态与交付不在产品层重复维护，唯一实现为 `soota.knowledge`。旧 Python 模块与命令在 `../lorehub/` 提供兼容。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
