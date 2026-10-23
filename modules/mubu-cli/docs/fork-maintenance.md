# Fork 状态、后续计划与上游同步

本项目是 `0xTotoroX/mubu-cli`，上游为 `liuboacean/mubu-integration`。第一批节点功能基于上游 v1.3.16 后的 `f2f0e53`，面向个人串行编辑。当前项目版本为 `1.4.0`，尚未发布；历史发布记录保留原样。

## 已发布功能

- 继承上游文档管理和 Markdown/OPML/FreeMind 导出能力，保留原 CLI 入口和密码/JWT 认证。
- 新增 `nodes`、`node-update`、`node-create`、`node-delete`，支持节点 ID、正文/描述分别修改、子节点位置及删除子树。
- 新增 `--auth desktop`：只读复用桌面会话，macOS App Store 版已实测，不要求应用常驻。
- 默认预览；真实写入前复核快照，保存操作记录，单次发送、读回核验，不自动整树覆盖。
- 155 项自动化测试通过，含上游原有 115 项；新增操作已在独立云端文档和网页界面验收。

上游旧功能通过回归测试，不表示本 fork 已把每条旧命令重新实机验收。

## 1.4.0 新增功能（待发布）

- 分支/深度读取、祖先路径、原始 HTML、顶层新增及子树移动/排序。
- 保留格式的唯一片段替换、追加文本和超链接；不支持任意富文本样式编辑。
- 节点图片上传、文档级附件上传和列表；附件以下载 SHA-256 核验。
- 只读 `auth-status`，补充实测 `Login Expired` 的桌面重新登录提示。
- Agent 模式：无交互 JSON 输出、搜索/导出完整性报告、禁止自动重发，以及操作记录只读查询与核验；见 [Agent 调用约定](agent-usage.md)。
- 独立的双语 Fork 首页放在 `.github/`，根目录 README 保留上游原文。
- 本地 Python 3.9/3.12 均 216 项测试通过，lint 通过；PNG/JPEG 与 TXT 上传、网页显示、附件下载哈希已有实测，本轮新增 Agent 调用及只读核验检查。

## 尚未完成或尚未验证

- 自动回滚、批量操作、任意富文本格式编辑尚未实现。Agent 可直接调用现有入口，暂不开发全局短命令安装。
- Windows/Linux 实机验收；所有图片/附件类型与会员配额组合未逐一实测。
- 用户真实会话过期后的桌面重新登录全过程；当前只验证真实服务对合成无效凭据的拒绝和提示。
- Mubu Sync 下载新增媒体与 Obsidian 显示，跨端链接打开。
- 服务端原子并发保护：实测服务端能接受旧版本更新，客户端检查不能消除竞争窗口。

当前范围明确排除 MCP、多人协作、数据库/知识库工作流和自动双向同步。

## 分支和版本职责

- `origin/main`：本 fork 的主线，保留自身功能和已发布历史。
- `upstream/main`：本地跟踪上游状态的远端引用，`fetch` 只更新引用，不改本 fork 主线。
- `codex/*`：功能或维护分支；完成验证后合入本 fork 的 `main`。
- 本 Fork 采用直接编号：当前 `1.4.0`，下一版 `1.4.1`；后续按自身发布节奏递增，不再使用 alpha/beta 后缀。
- Fork 发布标签继续使用 `totoro-v<版本>`，例如 `totoro-v1.4.0`，与上游标签区分。已发布的 `totoro-v1.4.0-alpha.1` 和上游原标签保留，不改写。
- 合入上游代码不要求立即改号或发布；准备交付新版本时更新版本字段和变更说明。上游基线单独记录，不沿用上游标签发布 Fork 产物。
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

## README 维护

- `.github/README.md` / `.github/README.zh-CN.md`：直接维护本 Fork 的介绍、三方对比、使用和参考来源；GitHub 默认优先展示 `.github/README.md`。
- 根目录 `README.md` / `README.zh-CN.md`：保留上游原文，当前与 [f2f0e53](https://github.com/liuboacean/mubu-integration/commit/f2f0e53af66447970a1f2664a10bfbbea3f1d406) 逐字节一致，随上游正常合并。

Fork 首页链接到根目录原文，不复制或拼接正文，也不再使用 README 生成脚本或额外快照。`.github/` 中指向仓库其他目录的相对链接需以 `../` 开头；中英文首页互链留在同目录。

每次同步上游，审查根目录 README 的合并结果，并复核 Fork 首页中的能力对比、上游基线和发布状态。功能对比需要按实际代码更新，不能只更换提交号。未提交的改动先妥善保留，再开始合并。

这种文件隔离能减少冲突，但不保证 Git 永远零冲突：上游若也新增 `.github/README.md`，需要人工整合；既往已发布的 Fork README 改动也可能影响第一次同步的三方合并。不要配置 `merge=ours` 或丢弃自己的提交来同步。其他代码与文档冲突仍需正常处理。
