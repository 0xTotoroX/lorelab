# Provider 与独立运行时

Soota 核心负责识别、能力选择、预算、任务和输出。OpenCLI、TikHub 是独立 Provider；Provider 之间不互相调用。路由层先匹配能力，再按保存的来源策略选择；初始默认 OpenCLI 优先。完整原生功能和重叠映射见 [功能并集](features.md)。

## 当前接入范围

| 能力 | OpenCLI | TikHub |
| --- | --- | --- |
| Bilibili BV / YouTube 单视频元数据 | 默认优先；缓存按浏览器上下文分区，默认保留 300 秒 | 显式选择或授权兜底，仍使用最新未废弃接口 |
| 视频元数据内容包 | `ingest --transcript none`，无需 TikHub Key | 可显式选择 |
| X 用户最近帖子 | 最多 200 条快照，保存正文、来源与时间 | 统一目录解析尚未接入；可单独 `api call` 获取原始响应 |
| YouTube 频道 / Bilibili UP 主目录 | 尚未接入可靠分页 | 保留分页、预算、检查点与续跑 |
| Bilibili / YouTube 字幕 | 默认优先；正文与时间戳规范化，轨道类型/实际语言未知 | 显式选择或授权兜底 |
| 音频、本地 ASR 流程 | 尚未接入音频下载 | 显式 ASR 模式或已授权的 auto 兜底 |

默认优先级是缓存、OpenCLI、已授权的 TikHub。相同能力不因 TikHub 已配置或有缓存而跳过 OpenCLI。

`api list/show/call` 始终是显式 TikHub 接口工具，不会转成浏览器调用。OpenCLI 自带的其他命令不等于 Soota 已接入它们。

## 路由和费用

`inspect` 初始默认 OpenCLI 优先；免费来源不可用时可按费用策略转入 TikHub，默认逐次询问付费。`--provider opencli` 严格只用 OpenCLI，除非显式指定 fallback；`--provider tikhub` 跳过 OpenCLI。保存 auto 付费策略会把省略 provider 时的默认来源改为 TikHub。缓存可零预算读取，`--max-cost` 是附加上限。

免费来源缺少能力、程序不存在或 Bridge 确认未连接时，才允许已授权的兜底；已确认没有可用字幕时也可按授权使用 TikHub。登录、验证码、权限、限流、超时、适配器加载失败、响应契约变化、profile 错误及 daemon 版本冲突都会停止，不切换来源、不在 Soota 层自动重试。上游程序本身可能有内部重试，Soota 的总超时限制其运行时间。

所有受控请求在发出前检查预算。`--max-cost 0` 即使遇到标价为 0 的 billed 接口也会拒绝；未知价格也会拒绝。TikHub 单价来自现有受控快照；预算是请求费用预估，不是服务端账单限额。`actual_cost_usd` 不冒充实际账单。

默认 `ingest` 的 `auto` 和 `captions-only` 都先使用 OpenCLI；有字幕就直接保存，不查询 TikHub 钱包或初始化其 SDK。显式 `--provider tikhub` 或保存的自动付费策略可跳过免费来源。auto 模式缺少字幕时按付款策略尝试 TikHub；零预算或严格 OpenCLI 模式保留元数据并返回 partial。`--transcript asr` 是明确要求音频转写，目前仍走具备音频能力的 TikHub 路径；显式 OpenCLI 无音频能力时会报错。目录费用同样受逐次确认或已保存的 auto 策略控制，累计预算可选。两种目录没有互换游标的契约，所以 `catalog --fallback` 目前拒绝执行。

## 最近快照、缓存和账号

OpenCLI 的 `twitter tweets` 没有可用的分页游标，也可能退出成功却仅返回部分帖子。因此 X 的 `completeness` 永远为 `unknown`，`stop_reason=bounded_snapshot`；任务执行完成不代表历史全量完成，空结果也不代表用户没有帖子。

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

`SOOTA_OPENCLI_BINARY` 和 `OPENCLI_PROFILE` 可覆盖对应配置。OpenCLI 使用已登录 Chrome 的 Browser Bridge。首次连接用上游 `opencli doctor`；Soota 不启动、关闭或升级浏览器扩展。`soota doctor` 只检查本机依赖，不能证明登录成功。

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
| `providers/opencli.py` | 只读命令白名单、输出规范化、缓存与快照 |
| `providers/opencli_context.py` | 浏览器上下文绑定与 daemon 版本门禁 |
| `providers/process.py` | 无 shell 的 argv 调用、输出上限、超时和取消 |
| `providers/opencli_runtime.py` | 外部/受管运行时选择、完整性校验、安装与回滚 |
| `runtime_cli.py` | 对外暴露运行时管理命令 |

契约参考：[OpenCLI v1.8.3](https://github.com/jackwener/OpenCLI/tree/v1.8.3)、[TikHub 官方 X 接口](https://docs.tikhub.io/191321711e0)。TikHub X 官方响应样例的 `data` 为空，尚不足以实现严格分页解析器；本轮没有发送收费请求来猜测结构。

## 字幕契约

OpenCLI 使用 `bilibili subtitle BV_ID --lang ... -f json` 和 `youtube transcript VIDEO_ID --mode raw --lang ... -f json`。字幕片段映射为稳定 seg ID 和毫秒时间戳，缓存按实际浏览器上下文及请求语言分区；没有字幕的结果不持久化成可用字幕缓存。上游可能选用另一种语言，JSON 不包含真实轨道类型/语言，故 `source=unknown`、`language=null`，不冒充人工字幕或请求语言。Bilibili 当前使用默认分P。运行时兼容检查也包含这两个命令。

字幕验收（2026-09-22）：151 项自动测试通过；本机 Bilibili 零预算实测保存 167 个片段。YouTube 接入的契约测试通过，但本机 1.8.3 上游实测报 `Caption URL returned empty response`，未误判为无字幕，也未进入付费兜底。
