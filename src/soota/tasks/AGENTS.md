# tasks/

> L2 | 父级：[项目约定](../../../AGENTS.md)

统一内容任务的输入、枚举、调度、获取编排与恢复。高层职责以 [docs/providers.md](../../../docs/providers.md) 为主源，对外契约以 [docs/tasks.md](../../../docs/tasks.md) 为主源。

## 成员与入口

- `__init__.py`：包入口。
- `models.py`：输入／目标、持久化并发设置与执行作用域、条目／任务状态；任务级进度和导出互斥锁不序列化。
- `inputs.py`：清单、链接、本地文件与旧包解析，来源标识和文件指纹。
- `entry.py`：`ingest` 参数验证、旧入口兼容和能力发现。
- `enumeration.py`：有序展开集合，复用目录／原生查询检查点。
- `scheduler.py`：最多 N 个在途条目，逐提交复制上下文，同一实际目录有序处理，中断时停止调度并等待写入结束。
- `runner.py`：`execute`／`resume`，串联获取、产物复用、步骤状态、全批预算与分析／导出接续。
- `acquire.py`：复用 Provider、原生绑定和媒体服务，返回正文、字幕、媒体及真实获取状态。
- `outputs.py`：字幕导出、图片、分析请求和带身份／指纹的分析提交。
- `state.py`：私有请求／输入文件、去重、锁内合并独立条目快照、任务记录保存及内容包文件锁。

并发 worker 只修改自己的 TaskItem；保存使用 `save_job(..., item=row)` 合并到当前任务。枚举、分析提交和最终状态归主执行线程。预算预留必须在实际请求前经过共享 `TaskBudget`，不能用单 worker 的局部费用替代全批上限。

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
