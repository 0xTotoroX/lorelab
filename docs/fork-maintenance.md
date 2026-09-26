# Fork 状态、后续计划与上游同步

本项目是 `0xTotoroX/mubu-integration`，上游为 `liuboacean/mubu-integration`。第一批节点功能基于上游 v1.3.16 后的 `f2f0e53`，面向个人串行编辑。公开预发布不代表稳定版。

## 已完成

- 继承上游文档管理和 Markdown/OPML/FreeMind 导出能力，保留原 CLI 入口和密码/JWT 认证。
- 新增 `nodes`、`node-update`、`node-create`、`node-delete`，支持节点 ID、正文/描述分别修改、子节点位置及删除子树。
- 新增 `--auth desktop`：只读复用桌面会话，macOS App Store 版已实测，不要求应用常驻。
- 默认预览；真实写入前复核快照，保存操作记录，单次发送、读回核验，不自动整树覆盖。
- 155 项自动化测试通过，含上游原有 115 项；新增操作已在独立云端文档和网页界面验收。

上游旧功能通过回归测试，不表示本 fork 已把每条旧命令重新实机验收。

## 尚未完成或尚未验证

- MCP、顶层新增节点、节点移动/排序、批量操作和自动撤销。
- 保留字段内部格式的富文本局部编辑；当前正文/描述替换为纯文本。
- 图片/附件的真实场景验收（只有未知字段保留的离线测试）。
- Windows/Linux 实机认证与写入验收；当前 macOS 登录记录解析也依赖应用存储格式。
- 可安装的 `mubu` 全局命令、PyPI/Homebrew 分发、自动升级；目前通过 Python 脚本运行。
- 自动登录、刷新桌面会话、Markdown 双向同步和离线协作。
- 服务端原子并发保护：实测服务端能接受旧版本更新，客户端的前置检查不能消除竞争窗口。

## 后续顺序（计划，尚未实施）

1. **先补可放心使用的边界**：真实富文本/图片附件文档测试、过期登录诊断、异常恢复说明；覆盖上游旧命令的关键实机行为。
2. **再补常用编辑操作**：顶层新增、节点移动/排序；研究保留格式的局部修改及可核验的撤销方案。
3. **再改善接入与分发**：可安装 CLI、按需提供共用同一库的 MCP；确定支持平台后补平台验收。
4. 批量编辑、长期双向同步和多人并发属于独立范围，先评估协议支持，不在第一版承诺。

## 分支和版本职责

- `origin/main`：本 fork 的主线，保留自身功能和已发布历史。
- `upstream/main`：本地跟踪上游状态的远端引用，`fetch` 只更新引用，不改本 fork 主线。
- `codex/*`：功能或维护分支；完成验证后合入本 fork 的 `main`。
- Fork 发布标签使用 `totoro-v<版本>`，例如 `totoro-v1.4.0-alpha.1`；上游原标签保留，不改写。
- 包版本表示本 fork 的版本，上游基线另行记录。版本号相同不代表两个仓库的功能相同。

上游更新不会自动改变本 fork 或已发布源码包。默认没有定时同步、自动合并或自动发布。

## 同步上游

先检查工作区与现有分支，已有变更必须保留。以下为工作区干净、主线已同步时的参考步骤：

```sh
git fetch origin --no-tags
git fetch upstream --no-tags
git switch main
git merge --ff-only origin/main
git switch -c codex/upstream-sync-YYYYMMDD
git merge --no-ff upstream/main
```

合并冲突逐项处理，保留本 fork 的节点模块、认证选择和版本标识；不要整文件“全部接受上游”。即使没有文本冲突，也要检查 API、认证、数据结构与重试语义的变化。

验证环境中的依赖应来自合并后的 requirements；运行自动化测试及 lint，协议发生变化时在独立测试文档中实测节点读写，确认后再合入 `main` 并发布新的 fork 版本。

```sh
PYTHONPATH=scripts .venv/bin/python -m pytest -q
.venv/bin/ruff check scripts
```

不要用 `reset --hard upstream/main`、强推或“丢弃自己的提交”来同步。已公开的提交、标签和发布产物不重写；有问题用修复提交和新版本处理。GitHub 的 Sync fork 并非必然丢改动，但它不能代替上述兼容性检查。
