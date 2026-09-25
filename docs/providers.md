# Provider 与独立运行时

Soota 核心负责识别、能力选择、预算、任务和输出。opencli-mcp、OpenCLI、TikHub 是独立 Provider；Provider 之间不互相调用。路由层先匹配能力，再按来源策略选择；初始顺序为 opencli-mcp → OpenCLI → 经授权的 TikHub。完整原生功能和重叠映射见 [功能并集](features.md)。

## 当前接入范围

| 能力 | opencli-mcp | OpenCLI | TikHub |
| --- | --- | --- | --- |
| Bilibili BV 元数据、字幕 | 优先；已接入只读适配器，实际字幕语言与轨道类型未知 | MCP 不可用或无字幕时继续尝试 | 显式选择或经授权兜底 |
| YouTube 元数据、字幕 | 当前没有已接入适配器，直接跳过 | 优先，字幕语言与轨道类型未知 | 显式选择或经授权兜底 |
| 视频元数据内容包 | 支持 Bilibili | 支持 Bilibili、YouTube | 可显式选择 |
| X 用户最近帖子 | 最多 100 条快照 | 最多 200 条快照 | 统一目录解析尚未接入，可用 `api call` 获取原始响应 |
| YouTube 频道 / Bilibili UP 主目录 | 未接入可续跑分页 | 未接入可续跑分页 | 保留分页、预算、检查点与续跑 |
| 音频、本地 ASR 流程 | 未接入音频下载 | 未接入音频下载 | 显式 ASR 模式或已授权的 auto 兜底 |

同一 Provider 内先查缓存；默认来源顺序是 opencli-mcp、OpenCLI、经授权的 TikHub。显式 `--provider` 严格选择指定来源，除非同时指定已支持的 fallback。

`api list/show/call` 始终是显式 TikHub 接口工具，不会转成浏览器调用。OpenCLI 自带的其他命令不等于 Soota 已接入它们。

## 路由和费用

`inspect` 按能力先用 opencli-mcp，再用 OpenCLI；免费来源不可用时可按费用策略转入 TikHub，默认逐次询问付费。`--provider opencli-mcp`、`--provider opencli` 或 `--provider tikhub` 严格选择一个来源；`--fallback tikhub` 只在支持的单视频流程中生效。`policy set --mode auto` 只改变轮到 TikHub 时的付费授权，不改来源顺序。可在 `config.toml` 的 `[routing]` 中显式设置 `default_provider`；旧付费策略文件中耦合的 `default_provider` 会在加载时忽略。缓存可零预算读取，`--max-cost` 是附加上限。

免费来源缺少能力、程序不存在或 Bridge 确认未连接时，才允许已授权的兜底；已确认没有可用字幕时也可按授权使用 TikHub。登录、验证码、权限、限流、超时、适配器加载失败、响应契约变化、profile 错误及 daemon 版本冲突都会停止，不切换来源、不在 Soota 层自动重试。上游程序本身可能有内部重试，Soota 的总超时限制其运行时间。

所有受控请求在发出前检查预算。`--max-cost 0` 即使遇到标价为 0 的 billed 接口也会拒绝；未知价格也会拒绝。TikHub 单价来自现有受控快照；预算是请求费用预估，不是服务端账单限额。`actual_cost_usd` 不冒充实际账单。

默认 `ingest` 的 `auto` 和 `captions-only` 在 Bilibili 先试 opencli-mcp，再试 OpenCLI；YouTube 跳过缺失的 MCP 适配器。有字幕就直接保存，不查询 TikHub 钱包。免费来源明确没有字幕时可继续下一来源；登录、限流、契约变化、请求后断线或超时都会停止。auto 模式缺少字幕时按付款策略尝试 TikHub；零预算或严格免费来源模式保留元数据并返回 partial。`--transcript asr` 仍走具备音频能力的 TikHub 路径。目录费用受同一付费策略控制；不同来源不能互换分页游标，所以 `catalog --fallback` 拒绝执行。

## 最近快照、缓存和账号

OpenCLI 的 `twitter tweets` 没有可用的分页游标；opencli-mcp 虽提供游标，但当前 Soota 只按最多 100 条保存最近快照，且上游可能静默返回部分帖子。因此 X 的 `completeness` 为 `unknown`，`stop_reason=bounded_snapshot`；任务执行完成不代表历史全量完成，空结果也不代表用户没有帖子。

每个新快照重新采集；`--incremental` 只按平台和帖子 ID 跳过同一来源、同一 Provider、同一浏览器上下文的已保存条目。不会因整页已存在而宣布追平，不写历史时间水位。X 不支持 `jobs resume`，重跑应创建新的快照。TikHub 老目录记录缺少 provider 字段时仍按 TikHub 解释，续跑不改变来源和页码。

元数据缓存保留 Provider、实际 context ID、运行时版本和采集时间。Soota 解析 `OPENCLI_CONFIG_DIR/browser-profiles.json` 的默认值与别名，固定实际 context ID 后再执行，防止默认 profile 或别名改绑后串用缓存。**同一浏览器上下文内更换网站登录账号无法自动识别**；此时应更换独立浏览器 profile，或关闭元数据缓存并使用非增量新任务。

## 配置

`~/.config/soota/config.toml` 可选：

```toml
[opencli]
# binary = "/absolute/path/to/opencli"  # 显式配置优先；此时不启用受管升级
# profile = "你的 profile 别名或 context ID"
timeout_seconds = 90
max_output_bytes = 8388608
metadata_cache_seconds = 300
```

`SOOTA_OPENCLI_BINARY` 和 `OPENCLI_PROFILE` 可覆盖对应配置。OpenCLI 使用已登录 Chrome 的 Browser Bridge。首次连接用上游 `opencli doctor`。opencli-mcp 使用自己的 Chrome 扩展和 Native Messaging 宿主，安装 Node.js 22+ 与扩展后运行 `opencli-mcp setup --clients none`，再用 `opencli-mcp doctor` 检查连接。Soota 不把它注册到 Codex；`soota doctor` 只检查程序是否安装，不能证明浏览器已连接或网站已登录。

```toml
[opencli_mcp]
# binary = "/absolute/path/to/opencli-mcp"
timeout_seconds = 180
max_output_bytes = 8388608
metadata_cache_seconds = 300

[routing]
default_provider = "auto"  # 或 opencli-mcp / opencli / tikhub
```

`SOOTA_OPENCLI_MCP_BINARY` 可覆盖 MCP 可执行文件路径。MCP 元数据和字幕缓存独立于 OpenCLI；切换浏览器登录账号时应清除相应缓存。当前核验 opencli-mcp `0.0.22`；三个站点命令在 Soota 白名单中，执行前还会核对服务版本、当前只读元数据和参数契约，发现同名本地 adapter 覆盖就停止。上游升级后需重新核验契约。Soota 不暴露 opencli-mcp 的通用浏览器写操作。

## 独立升级与回滚

```bash
uv run soota runtime status --json
uv run soota runtime check-update --json
uv run soota runtime update --version 1.8.7 --json
uv run soota runtime rollback --json
```

- 默认使用 PATH 中现有 OpenCLI；Soota 不覆盖、修补或 `npm -g` 更新它。
- `update` 只接受完整版本号。从官方 npm 下载并验证包的 SHA-512，安装到 Soota `data_dir/runtimes/opencli/versions/版本号`，禁用 npm 安装脚本，再检查版本、只读命令和 JSON 列契约；成功后原子切换指针。网络、安装或契约失败不切换。
- 保留上一受管版本；第一次受管安装的 rollback 返回原有 PATH 安装。升级不更改 Python 代码或 TikHub SDK，也不自动更新浏览器扩展。独立更新仍受接口兼容性约束。
- 运行时互斥锁避免 Soota 正在执行命令时升级。外部 OpenCLI 不受该锁管理；采集前只读检查 daemon 版本，若不同立即停止，防止 OpenCLI 自动接管用户的旧 daemon。应等待外部采集结束后手动切换 daemon，或 rollback。不要为了使用新版本中断已有任务。
- 升级检查不访问网站，不证明站点可用；更新后用一条已知公开视频的零预算 `inspect` 验证。全局程序有本地补丁时，不会把补丁复制到受管官方包。
- TikHub SDK 的升级使用开发流程：编辑锁定版本、`uv lock`、测试、核查该版许可、Git commit，再 `uv sync`；不在运行中的 Python 环境自我升级。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `providers/router.py` | 能力选择、元数据兜底和请求预算 |
| `providers/mcp_client.py` | 本地 stdio MCP 会话、响应大小与超时控制 |
| `providers/opencli_mcp.py` | opencli-mcp 只读命令白名单、结果规范化和缓存 |
| `providers/opencli.py` | 只读命令白名单、输出规范化、缓存与快照 |
| `providers/opencli_context.py` | 浏览器上下文绑定与 daemon 版本门禁 |
| `providers/process.py` | 无 shell 的 argv 调用、输出上限、超时和取消 |
| `providers/opencli_runtime.py` | 外部/受管运行时选择、完整性校验、安装与回滚 |
| `runtime_cli.py` | 对外暴露运行时管理命令 |

契约参考：[OpenCLI v1.8.3](https://github.com/jackwener/OpenCLI/tree/v1.8.3)、[TikHub 官方 X 接口](https://docs.tikhub.io/191321711e0)。TikHub X 官方响应样例的 `data` 为空，尚不足以实现严格分页解析器；本轮没有发送收费请求来猜测结构。

## 字幕契约

OpenCLI 使用 `bilibili subtitle BV_ID --lang ... -f json` 和 `youtube transcript VIDEO_ID --mode raw --lang ... -f json`。字幕片段映射为稳定 seg ID 和毫秒时间戳，缓存按实际浏览器上下文及请求语言分区；没有字幕的结果不持久化成可用字幕缓存。上游可能选用另一种语言，JSON 不包含真实轨道类型/语言，故 `source=unknown`、`language=null`，不冒充人工字幕或请求语言。Bilibili 当前使用默认分P。运行时兼容检查也包含这两个命令。

字幕验收（2026-09-22）：151 项自动测试通过；本机 Bilibili 零预算实测保存 167 个片段。YouTube 接入的契约测试通过，但本机 1.8.3 上游实测报 `Caption URL returned empty response`，未误判为无字幕，也未进入付费兜底。
