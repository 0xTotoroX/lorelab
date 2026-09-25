# 三来源功能映射与费用策略

Soota 的 `features` 是统一功能注册表：列出 Soota 已核验的 opencli-mcp 只读命令，动态读取 OpenCLI 命令元数据，再加入随包维护的 TikHub OpenAPI 注册表。原生入口保留三者已接入的能力；明确核验为同一用途的功能提供统一入口与来源顺序。功能清单可调用不代表每个网站都已联网验收，登录、权限、地区和上游改版仍可能影响执行。

## 功能范围

2026-09-22 本机 OpenCLI 1.8.3 的 `list -f json` 登记 **1,050 条命令、162 个入口**：803 条 read、247 条 write；757 条需要浏览器，293 条不需要。范围包括搜索、用户资料、内容详情、时间线、评论、字幕、下载、热榜、开发者工具，以及发布和修改。`read` 仍可能下载文件；OpenCLI 不收 TikHub API 费用，但它调用的其他服务是否收费不能从清单推定。

该统计不包含 OpenCLI 自身的 daemon、plugin、browser 管理命令或外部 CLI passthrough。运行时升级后重新 `features list` 就会读取新功能；不需要把 1,050 条命令硬编码进 Soota。

TikHub 快照含 1,063 条版本记录，选取新版后为 **964 个接口入口**，其中 900 个当前内容查询、63 个辅助接口、1 个已废弃入口。内容查询沿用 `api` 的验证与计费；辅助接口在 `features` 下显式 `--allow-write` 才能执行，未知价格仍停止，已废弃接口不可执行。该名称表示对非普通读取操作的显式选择，不代表每个辅助接口都会写入。

opencli-mcp 当前接入 3 个只读站点命令：Bilibili 视频详情、字幕和 X 最近帖子。按上文 OpenCLI 1.8.3 快照计算，再加上 11 个跨 Provider 的统一入口，合计 **2,028 个入口**；其中 `bilibili.video.detail` 有三种方案，其余统一入口维持现有映射。该数量是功能入口数，实时运行时或上游接口变更后以 `features list` 为准。

## 发现、查看、调用

在仓库目录运行，或安装后省略 `uv run`：

```bash
uv run soota features list --limit 50 --json
uv run soota features list --site youtube --json
uv run soota features list --provider opencli-mcp --json
uv run soota features list --provider opencli --search subtitle --json
uv run soota features list --provider tikhub --search search --json
uv run soota features list --offset 50 --limit 50 --json
uv run soota features show twitter.profile --json
uv run soota features show opencli.bilibili.subtitle --json
uv run soota features show opencli-mcp.bilibili.subtitle --json
uv run soota features show tikhub.twitter.web.fetch_user_profile --json
```

每个条目都有 `plans`，说明对应来源和操作。OpenCLI、TikHub 的 `show` 提供各自参数契约；opencli-mcp 的 `show` 标明已核验的站点命令，参数可在 `call --dry-run` 中核对。原生 ID 分别以 `opencli-mcp.`、`opencli.`、`tikhub.` 开头。指定原生 ID 就是明确选择该 Provider，不再自动替换。

```bash
# 默认按已核验能力选择来源
uv run soota features call twitter.profile --param username=jack --json

# 只预览参数和所选方案，不调用业务接口
uv run soota features call twitter.profile --param username=jack --dry-run --json

# 明确选择 TikHub；默认仍会逐次询问是否付费
uv run soota features call twitter.profile --param username=jack --provider tikhub --max-cost 0.01 --json

# 字幕原生结果；需要已登录浏览器以及可用字幕
uv run soota features call opencli.bilibili.subtitle --param bvid=BV1M1421t7hT --json
uv run soota features call opencli-mcp.bilibili.subtitle \
  --param bvid=BV1M1421t7hT --output ./subtitle-native.json --json

# 搜索支持 top/latest，不承诺两家结果或分页完全一致
uv run soota features call twitter.post.search --param 'query=from:jack' --param sort=latest --json
```

复杂参数可用 `--params-file params.json`，TikHub JSON 请求体用 `--body body.json`。字符串 ID 在 JSON 中保留引号；布尔参数写 `true` / `false`。未知参数、错误类型、重复参数在执行前拒绝。写入操作先 `show`、`--dry-run` 核对，再明确加 `--allow-write`。`features call --output` 将脱敏原生响应保存到新文件，stdout 只返回路径与状态。结果仍保持原生结构，`output_contract=provider_native`；若需要 Soota 的标准字幕、Markdown、目录续跑，使用 `ingest` / `catalog`。

## 已核验的重叠映射

默认顺序为 opencli-mcp → OpenCLI → 经授权的 TikHub。先按能力筛选：YouTube 没有已接入的 MCP 适配器，直接从 OpenCLI 开始。`--provider opencli-mcp`、`--provider opencli`、`--provider tikhub` 严格选择对应来源；`--provider auto` 明确恢复默认顺序。自动付费模式不改变来源排序；只有轮到 TikHub 时才改变付费确认方式。

| 统一入口 | 共同输入 | 语义范围 |
|---|---|---|
| `twitter.profile` | `username` | 用户资料，允许去掉前导 @ |
| `instagram.profile` | `username` | 用户名查询，不是数字用户 ID |
| `reddit.profile` | `username` | 用户资料，允许去掉 u/ |
| `tiktok.profile` | `username` | 映射到 TikHub `uniqueId` |
| `weibo.profile` | `uid` | 仅数字 UID |
| `zhihu.answer.detail` | `answer_id` | 数字回答 ID，全文原始格式不同 |
| `instagram.user.search` | `query` | 首批用户搜索，无统一游标 |
| `twitter.post.search` | `query`，可选 `sort` | 首批帖子；top/latest，无统一条数保证 |
| `bilibili.video.detail` | `url` | 标准视频链接 |
| `youtube.video.detail` | `url` | 标准视频链接 |
| `xiaohongshu.note.detail` | `url` | 已展开官方笔记链接，含 xsec_token；输出脱敏 |

仅在请求发送前确认免费来源不可用时，统一入口才考虑下一方案。执行失败、限流、登录问题、无效 JSON、断线后结果不确定都不会触发盲目重试或自动收费。尚未核验等价关系的命令保留各自原生入口，不按同名猜测互换参数或分页。

已有标准流程也遵循此优先级：Bilibili 元数据与字幕先试 opencli-mcp，YouTube 从 OpenCLI 开始，TikHub 保留独立实现。X 的 opencli-mcp/OpenCLI 目录都是最近快照，YouTube/Bilibili 的可续跑目录使用 TikHub；不能交换游标。其他上游命令并不自动等于 Soota 的可续跑历史目录。

## 两种付费模式

```bash
# 查看当前策略；不改配置
uv run soota policy show --json

# 默认模式：免费来源优先，每次 TikHub 计费请求都询问
uv run soota policy set --mode ask

# 保持来源顺序，轮到 TikHub 时自动付费；余额触及 5 USD 就暂停
uv run soota policy set --mode auto --min-balance 5

# 保持来源顺序，轮到 TikHub 时自动付费；不设余额限制
uv run soota policy set --mode auto --no-balance-limit
```

配置保存在 `~/.config/soota/payment-policy.json`（或 `SOOTA_CONFIG_DIR`），不会改写现有 `config.toml`。本次实现没有替用户启用自动收费；初始模式仍为 ask。

ask 在交互终端把接口和预估 USD 费用写到 stderr，默认 `N`，输入 `y` / `yes` 才执行当前请求。一个字幕任务可能含多次请求，会分别询问。stdin 不是终端时返回 `payment_required` 并停止；向管道输入 `yes` 不会自动授权。JSON stdout 保持单个文档。缓存命中与明确免费请求无需付费确认。

auto 配置必须明确给出 `--min-balance` 或 `--no-balance-limit`。余额阈值只使用 TikHub 的 **USD 付费余额 balance**，不加免费额度。每次付费请求前重新读取余额；若 `balance - 本次预估费用 <= 阈值`，或余额无法确认，则暂停。免费余额和定价元数据接口在本机跨进程限速；不缓存旧钱包当成当前余额。

`--max-cost USD` 是可选附加上限，不替代 ask 的逐次确认；0 明确禁止计费接口。目录上限累计计算，续跑不清零，省略新上限保留旧值；旧任务的来源和预算不被新策略覆盖。自动模式仍受该预算、参数校验和登录限制约束。额度预留和余额检查基于预估费用，不是服务端原子扣费控制，其他客户端同时消费或上游涨价仍可能改变实际余额。

## 代码边界

- `features.py`：功能发现、原生入口和统一映射路由。
- `feature_aliases.py`：人工核验的参数映射与语义限制。
- `features_cli.py`：功能 list/show/call 命令。
- `providers/opencli_commands.py`：动态元数据、参数验证、无 shell 的命令转发。
- `providers/mcp_client.py` 与 `providers/opencli_mcp.py`：内部 stdio 客户端、只读能力白名单和规范化。
- `billing.py`：每请求付费确认、余额暂停和免费元数据限速。
- `policy_cli.py`：策略显示和原子保存。
- `providers/tikhub/client.py`：计费 gate 与 HTTP 发送的统一边界，禁用隐式重试。

[OpenCLI 上游](https://github.com/jackwener/OpenCLI) · [TikHub 用户信息](https://docs.tikhub.io/186826050e0) · [终端教程](terminal-tutorial.md) · [Provider 架构](providers.md)
