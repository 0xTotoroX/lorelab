# knowledge/

> L2 | 父级: ../AGENTS.md

LoreLab 负责知识流程的唯一实现；采集任务仍归 Soota 的 `tasks/`，单来源分析与产物校验调用相邻 `content/`，跨来源知识文章与学习任务在此独立保存状态。此模块复用 Soota 内容包契约，不调用服务私有 API。

- `__init__.py`：知识模块入口。
- `cli.py`：LoreLab knowledge/study 参数、配置及 init/batch 别名。
- `runtime.py`：独立 CLI 发现或受管绑定调用；旧配置兼容；JSON 回执与无 shell 的 argv。
- `workflow.py`：文章批次、可选组合交付、核对与授权清理入口。
- `bundles.py`：已验证 v2 正文/字幕包输入，源包只读并保留指纹。
- `workflow_sources.py`：Cubox 来源与保护范围、补抓及 LoreLab content 采集/分析任务交接。
- `workflow_review.py`：来源覆盖、证据映射、Agent 提交与完成产物冻结。
- `workflow_publish.py`：Markdown 交付与幕布单次派发、整树核对；保持旧共享锁。
- `workflow_cleanup.py`：仅 Cubox 的适用授权清理和删除回查，未知结果不重发。
- `workflow_state.py`：不可变任务、路径、指纹、锁和旧 schema 默认语义。
- `study.py`：只读选定文章、冻结学习大纲和按需幕布交付。

默认采集仍到 context 结束；用户明确要求知识整理才调用此流程。语义理解归 Skill/Agent，程序不自动生成文章。旧 JOB 按绝对路径原地读取，不搬迁来源/回执或改写冻结 spec；旧任务缺少 with_outline/cleanup_after 时保留组合交付门槛。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
