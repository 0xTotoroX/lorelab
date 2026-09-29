# Provider 与独立运行时

Soota 核心负责识别、能力选择、预算、任务和输出。opencli-mcp、OpenCLI、内置 `soota`、TikHub 是独立 Provider；Provider 之间不互相调用。路由层先匹配能力，再按来源策略选择；当前顺序为 OpenCLI → soota → 经授权的 TikHub，opencli-mcp 默认停用。业务入口和按需发现方式见 [功能入口与费用策略](features.md)。

## 当前接入范围

| 能力 | OpenCLI | TikHub |
| --- | --- | --- |
| Bilibili / YouTube 元数据与字幕 | 优先；轨道类型与真实语言未标明时保留未知 | 显式选择或经授权兜底 |
| B站同作者同一期 YouTube 字幕优先 | 可选 `--prefer-youtube`，有频道和同一期视频依据才替换 | 未接入 |
| X 用户最近帖子 | 最多 200 条快照，完整性未知 | 统一目录解析尚未接入，可用 `api call` 获取原始响应 |
| YouTube 频道 / Bilibili UP 主目录 | 未接入可续跑分页 | 保留分页、预算、检查点与续跑 |
| 音频、本地 ASR 流程 | 未接入音频下载 | 显式 ASR 或已授权的 auto 兜底 |

同一 Provider 内先查缓存。显式 `--provider` 严格选择指定来源，除非同时指定已支持的 fallback。字幕跨平台选择及推广过滤见 [字幕选择与过滤](subtitle-selection.md)。

`api list/show/call` 始终是显式 TikHub 接口工具，不会转成浏览器调用。OpenCLI 自带的其他命令不等于 Soota 已接入它们。

### 内置 soota Provider

当前只支持 YouTube 单视频元数据和字幕，通过外部 yt-dlp 执行。`inspect`、`ingest` 及 `youtube.video.detail` 按能力使用它；没有接入目录、音频下载或其他平台。`official` 表示网站的非自动字幕轨道，不保证作者上传前未使用 AI。

字幕优先匹配请求语言，其次同语系；同一语言匹配级别优先非自动轨道。没有匹配语言时选择其他现有轨道，输出记录实际语言和轨道类型。不保存签名字幕 URL、请求头或 Cookie；临时 JSON3 下载后转换为标准内容包并删除。缓存按程序路径、浏览器选择和请求语言的散列隔离，保留 300 秒；同一 profile 切换账号后需使用新的缓存目录。

`SOOTA_YTDLP_BINARY` 指定程序，默认 PATH 中的 `yt-dlp`；`SOOTA_YTDLP_COOKIES_BROWSER` 使用 yt-dlp 的浏览器/profile 语法，默认 `chrome`，空字符串关闭 Cookie 读取。个人选择仅从环境变量注入。Provider 算法随 Soota 更新；外部 yt-dlp 由其原安装工具维护，`updates apply` 不升级它。

## 路由和费用

`inspect` 按能力先用 OpenCLI；免费来源不可用时可按费用策略转入 TikHub，默认逐次询问付费。`--provider opencli`、`--provider soota` 或 `--provider tikhub` 严格选择一个来源；`--fallback tikhub` 只在支持的单视频流程中生效。`policy set --mode auto` 只改变轮到 TikHub 时的付费授权，不改来源顺序。可在 `config.toml` 的 `[routing]` 中显式设置 `default_provider`；旧付费策略文件中耦合的 `default_provider` 会在加载时忽略。缓存可零预算读取，`--max-cost` 是附加上限。

免费来源缺少能力、程序不存在或 Bridge 确认未连接时，才允许已授权的兜底；已确认没有可用字幕时也可按授权使用 TikHub。YouTube 的已知 `Caption URL returned empty response` 会在 auto 模式继续 soota；两层免费来源均无可用结果后，仍需经过 TikHub 费用策略。显式 OpenCLI 不自动转到 soota。登录、验证码、权限、限流、超时、适配器加载失败、响应契约变化、profile 错误及 daemon 版本冲突都会停止，不切换来源、不在 Soota 层自动重试。上游程序本身可能有内部重试，Soota 的总超时限制其运行时间。

所有受控请求在发出前检查预算。`--max-cost 0` 即使遇到标价为 0 的 billed 接口也会拒绝；未知价格也会拒绝。TikHub 单价来自现有受控快照；预算是请求费用预估，不是服务端账单限额。`actual_cost_usd` 不冒充实际账单。

默认 `ingest` 的 `auto` 和 `captions-only` 在 Bilibili 和 YouTube 都先试 OpenCLI。有字幕就直接保存，不查询 TikHub 钱包。YouTube 在 OpenCLI 不可用或字幕缺失时继续尝试 soota。免费来源明确没有字幕时可继续下一来源；登录、限流、契约变化、请求后断线或超时都会停止。auto 模式缺少字幕时按付款策略尝试 TikHub；零预算或严格免费来源模式保留元数据并返回 partial。`--transcript asr` 仍走具备音频能力的 TikHub 路径。目录费用受同一付费策略控制；不同来源不能互换分页游标，所以 `catalog --fallback` 拒绝执行。

## 最近快照、缓存和账号

OpenCLI 的 `twitter tweets` 没有可用的分页游标，上游也可能返回部分帖子。因此 X 的 `completeness` 为 `unknown`，`stop_reason=bounded_snapshot`；任务执行完成不代表历史全量完成，空结果也不代表用户没有帖子。

每个新快照重新采集；`--incremental` 只按平台和帖子 ID 跳过同一来源、同一 Provider、同一浏览器上下文的已保存条目。不会因整页已存在而宣布追平，不写历史时间水位。X 不支持 `jobs resume`，重跑应创建新的快照。TikHub 老目录记录缺少 provider 字段时仍按 TikHub 解释，续跑不改变来源和页码。

OpenCLI 元数据缓存保留 Provider、实际 context ID、运行时版本和采集时间。Soota 解析 `OPENCLI_CONFIG_DIR/browser-profiles.json` 的默认值与别名，固定实际 context ID 后再执行，防止默认 profile 或别名改绑后串用缓存。**同一浏览器上下文内更换网站登录账号无法自动识别**；此时应更换独立浏览器 profile，或关闭元数据缓存并使用非增量新任务。

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

`SOOTA_OPENCLI_BINARY` 和 `OPENCLI_PROFILE` 可覆盖对应配置。OpenCLI 使用已登录 Chrome 的 Browser Bridge。`soota runtime connect` 启动所选运行时并等待扩展连接；`soota doctor` 的程序安装检查不等于网站登录已验证。

```toml
[opencli_mcp]
enabled = false

[routing]
default_provider = "auto"  # 或 opencli / soota / tikhub
```

MCP 默认停用：自动路由跳过、功能清单隐藏，显式选择及 `mcp search/run` 在启动进程前拒绝。保留的代码供兼容性研究，普通任务不启用；不卸载浏览器扩展或影响其他客户端。Soota 命令结束后不持有 MCP 会话。

旧版要求服务端版本字符串恰好为 `0.0.22`，这是 Soota 客户端的硬编码检查，已移除。保留的实验客户端校验服务身份、实时只读标记和参数契约，不因版本号变新而拒绝；这不表示所有未来版本已经通过真实网站验收。

## 独立升级与回滚

```bash
uv run soota updates check --json
uv run soota runtime status --json
uv run soota runtime check-update --json
uv run soota runtime update --json
uv run soota runtime connect --json
uv run soota runtime rollback --json
```

- 未选择受管版本时使用 PATH 中现有 OpenCLI；Soota 不覆盖、修补或 `npm -g` 更新全局安装。
- `update` 省略版本号时查询最新稳定版；也可 `--version 完整版本号` 固定版本。从官方 npm 下载并验证包的 SHA-512，安装到 Soota `data_dir/runtimes/opencli/versions/版本号`，禁用 npm 安装脚本，再检查版本、只读命令和 JSON 列契约；成功后原子切换指针。网络、安装或契约失败不切换。
- 受管安装可应用已确认的局部兼容修复，包括媒体导航和 YouTube JSON3 字幕请求不带 `pot` 时被误过滤的问题。字幕补丁仅移除强制 `pot` 检查，保留视频 ID、字幕格式和原有语言筛选；不删除实际请求上的令牌。只匹配已知上游代码，标记修改来源并记录 `soota-compatibility.json`；上游代码变化时不猜测替换，也不仅因版本变新拒绝安装。全局安装不改动。
- 保留上一受管版本；OpenCLI 第一次受管安装的 rollback 返回原有 PATH 安装。`runtime update/rollback` 仅管理 OpenCLI，关闭自动更新后才能持续固定旧版本。独立更新仍受接口兼容性约束。
- 运行时互斥锁避免 Soota 正在执行命令时升级。外部 OpenCLI 不受该锁管理；采集前只读检查 daemon 版本，若不同立即停止，防止 OpenCLI 自动接管用户的旧 daemon。应等待外部采集结束后运行 `soota runtime connect` 切换空闲 daemon，或 rollback。不要为了使用新版本中断已有任务。
- 升级检查不访问网站，不证明站点可用；更新后用一条已知公开视频的零预算 `inspect` 验证。全局程序有本地补丁时，不会把补丁复制到受管官方包。
- 在线采集/调用前默认更新三个 Provider，或执行 `soota updates apply --json`。检查官方 npm／PyPI 最新发布包；不跟随 GitHub 未发布提交。`updates check` 保持只读。检查失败、安装失败或入口不兼容会报告，不重复执行采集或收费请求。
- opencli-mcp 同样隔离安装，校验 `--version` 和 `stdio` 入口；安装不执行 setup、不启动 MCP 会话，也不改变 `enabled=false`。浏览器扩展与 Native Messaging host 的注册不属于包自动更新范围。
- TikHub SDK 使用 uv 在 `data_dir/runtimes/tikhub/versions/版本号` 创建独立 Python 环境，从 PyPI 安装 wheel；通过离线 HTTP 模拟验证后切换 active 指针。实际请求由该环境的短生命周期子进程执行，密钥只经 stdin 传递，禁止 SDK 自动重试。付费确认、余额门槛和请求记账仍在 Soota 主进程。项目锁文件中的 SDK 作为未启用受管环境时的后备，不因运行时升级改写。
- 新版包更新不代表 TikHub 接口注册表自动增加功能；打包的注册表、价格与业务解析器仍随 Soota 维护。SDK 的离线验证也不能代替真实站点验证。
- `[updates] enabled = false` 或 `SOOTA_AUTO_UPDATE=false` 可关闭自动更新；`interval_seconds` 默认 0，每次在线任务检查，可设置更长间隔。`updates apply` 忽略开关和间隔强制检查。程序未运行时没有后台更新任务。
- 显式设置 OpenCLI/MCP `binary` 或对应环境变量时，该运行时由用户管理，自动更新跳过并报告。默认受管安装不覆盖全局 npm 或当前 Soota Python 环境。更新期间的并发采集可能被运行时锁拒绝，应等更新完成再执行；不会中断已有浏览器任务。
- `updates check` 只读查询三个 Provider 的 npm／PyPI 包版本及 GitHub 默认分支。分支有新提交、包有新版和 Soota 已核验兼容是三件不同的事；此命令不安装、不切换运行时，也不同步上游仓库备份。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `providers/router.py` | 能力选择、元数据兜底和请求预算 |
| `mcp_cli.py` | 按需发现并调用 MCP 只读站点命令 |
| `providers/mcp_contract.py` | 将上游参数描述转换为 JSON Schema 并验证调用 |
| `providers/mcp_client.py` | 本地 stdio MCP 会话、响应大小与超时控制 |
| `providers/opencli_mcp.py` | opencli-mcp 只读命令白名单、结果规范化和缓存 |
| `providers/soota.py` | 内置采集算法、yt-dlp 字幕选择、缓存与 JSON3 规范化 |
| `providers/opencli.py` | 只读命令白名单、输出规范化、缓存与快照 |
| `providers/opencli_context.py` | 浏览器上下文绑定与 daemon 版本门禁 |
| `providers/process.py` | 无 shell 的 argv 调用、输出上限、超时和取消 |
| `providers/opencli_runtime.py` | 外部/受管运行时选择、完整性校验、安装与回滚 |
| `providers/opencli_patches.py` | 对受管运行时应用已匹配的媒体导航与 YouTube 字幕过滤修复 |
| `counterpart.py` | 同名频道发现、身份与同一期视频验证 |
| `transcripts/promotions.py` | 社区及人工区间过滤，保留原片段编号与时间 |
| `runtime_cli.py` | 对外暴露运行时管理命令 |
| `updates.py`、`updates_cli.py` | 仓库更新查询与包更新 CLI 入口 |
| `auto_updates.py` | 在线任务前的自动检查、更新锁、失败报告和检查间隔 |
| `providers/managed.py` | MCP 与 TikHub 独立安装、离线验证和运行时绑定 |
| `providers/tikhub_worker.py`、`providers/tikhub/managed_client.py` | 经 stdin 传递请求的隔离 SDK 子进程桥接 |

契约参考：[OpenCLI v1.8.3](https://github.com/jackwener/OpenCLI/tree/v1.8.3)、[TikHub 官方 X 接口](https://docs.tikhub.io/191321711e0)。TikHub X 官方响应样例的 `data` 为空，尚不足以实现严格分页解析器；本轮没有发送收费请求来猜测结构。

## 字幕契约

OpenCLI 使用 `bilibili subtitle BV_ID --lang ... -f json` 和 `youtube transcript VIDEO_ID --mode raw --lang ... -f json`。字幕片段映射为稳定 seg ID 和毫秒时间戳，缓存按实际浏览器上下文及请求语言分区；没有字幕的结果不持久化成可用字幕缓存。上游可能选用另一种语言，JSON 不包含真实轨道类型/语言，故 `source=unknown`、`language=null`，不冒充人工字幕或请求语言。Bilibili 当前使用默认分P。运行时兼容检查也包含这两个命令。

自动测试覆盖适配器契约与故障分支；真实可用性还取决于浏览器版本、登录状态和网站响应。
