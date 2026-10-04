# Soota

给 Soota 一个链接：获取字幕或转写，保存可追溯的 context 正文。

Soota 是本地优先的内容摄取 CLI：优先使用 OpenCLI 的已核验免费能力，再由 `yt-dlp` Provider 获取 YouTube/Bilibili 字幕，字幕获取失败且符合兜底条件时按费用策略使用 TikHub；确认无字幕则直接下载音频、本地转写，并为 YouTube、Bilibili 提供字幕、ASR 和 Markdown 流程。Codex Skill 把自然语言任务变成 `soota` 命令。opencli-mcp 当前默认停用，不参与自动路由。

已接入 OpenCLI 的 X 最近快照、Bilibili 和 YouTube 视频元数据及字幕；还提供可选的 B站同作者同一期 YouTube 字幕优先、推广片段过滤、11 个统一业务入口、TikHub 接口封装、逐次确认/自动付费策略，三个外部 Provider 的默认自动更新，以及 OpenCLI 的独立升级/回滚。完整命令见 [功能映射与费用策略](docs/features.md)、[终端参考教程](docs/terminal-tutorial.md) 和 [Provider 架构与处理流程](docs/providers.md#处理流程与职责)。接口版本和平台能力清单见 [TikHub 接口说明](docs/tikhub-api.md)。

## 安装

需要 Python 3.12+。音频处理需要 ffmpeg；本地转写支持 `whisper` CLI、`faster-whisper` 和 Apple Silicon 上的 `mlx_whisper` CLI，默认模型为 `base`。MLX 的安装与配置见[本地转写引擎](docs/terminal-tutorial.md#本地转写引擎)。纯 API 查询不需要这些音频工具。

```bash
cd /path/to/soota
uv sync --extra dev
uv run soota doctor --json
```

OpenCLI 需要 Node.js、Chrome 和 Browser Bridge 扩展。可用 `uv run soota runtime update --json` 安装最新稳定运行时，再用 `uv run soota runtime connect --json` 启动所选版本并等待扩展连接。无需安装 opencli-mcp。

`yt-dlp` Provider 需要 PATH 中可用的 `yt-dlp`。默认读取 Chrome 登录态；`SOOTA_YTDLP_COOKIES_BROWSER` 可指定 yt-dlp 浏览器/profile，设为空可关闭 Cookie 读取，`SOOTA_YTDLP_BINARY` 可指定程序路径。`captions-only` 只下载字幕；`auto` 确认无字幕时会下载音频并本地转写。可显式使用 `soota ingest "视频 URL" --provider yt-dlp --transcript captions-only --max-cost 0 --json`，支持 YouTube 和 B 站。yt-dlp 由原安装工具维护，不在三个外部 Provider 的自动更新范围内。

音频来源默认是 yt-dlp，可用 `--audio-provider downie` 明确选择本机 Downie，或 `--audio-provider tikhub` 选择付费音频接口。Downie 的一次性完成回调设置及当前 CLI 流程图见 [Provider 路由](docs/providers.md#路由和费用)。

TikHub API Key 只从环境变量或 macOS Keychain 读取：

```bash
export TIKHUB_API_KEY="..."   # 不要把 Key 发给聊天或写入 Git
# 或：
security add-generic-password -s soota.tikhub -a api_key -w
```

## 命令

零费用快照示例：`uv run soota catalog "https://x.com/USERNAME" --max-items 50 --max-cost 0 --json`。完整性未知，不代表全部历史。

```bash
uv run soota doctor --json
uv run soota updates check --json
uv run soota platforms --json
uv run soota api list --platform bilibili --task detail --json
uv run soota api show bilibili.web.fetch_one_video --json
uv run soota inspect "URL" --json
uv run soota estimate "URL" --mode ingest --json
uv run soota catalog "频道或 UP 主 URL" --dry-run --json
uv run soota ingest "URL" --transcript auto --max-cost 0.05 --output PATH --json
uv run soota render --bundle PATH/manifest.json --analysis analysis.json
uv run soota jobs list --json
uv run soota jobs resume JOB_ID --json
```

字幕模式：`auto`、`captions-only`、`asr`、`none`。默认按能力依次尝试 OpenCLI、经授权的 TikHub。`policy set --mode auto` 只改变轮到 TikHub 时的付费方式，不改变来源顺序；`--provider tikhub` 可单次指定。`--max-cost 0` 禁止计费请求。

B站字幕可加 `--prefer-youtube`：匹配同名频道和同一期视频后优先使用 YouTube，并默认排除已有推广标注。`--no-prefer-youtube` 关闭跨平台检查，`--keep-promotions` 保留推广。过滤保留原字幕供追溯；无标注不代表无推广。详细使用与限制见 [字幕选择与过滤](docs/subtitle-selection.md)。

`--json` 时 stdout 只有一个 JSON 文档；日志和警告在 stderr。

`updates check` 只读检查三个 Provider 的本机版本、npm／PyPI 最新包版本，以及上游主分支相对本机版本标签的提交关系。仓库有新提交不一定代表已有新版可安装；此命令也不会更新程序或同步备份仓库。

执行在线采集、接口调用或目录续跑前，Soota 默认检查三个 Provider 并安装 npm／PyPI 最新已发布包。可用 `soota updates apply --json` 立即检查并更新；帮助、预估、离线预览和笔记渲染不会触发更新。首次运行需要 npm、Node.js 和 uv，并可能花几分钟安装。MCP 包即使更新，接入仍保持停用；浏览器扩展不会自动更新。更新失败会报告原因，已经安装的版本保留。

`SOOTA_AUTO_UPDATE=false` 可关闭自动更新；`config.toml` 的 `[updates] interval_seconds = 3600` 可将检查间隔改为一小时，默认 `0` 表示每次在线任务检查。固定版本或执行 `runtime rollback` 后若要继续使用该版，请关闭自动更新。安装位置、外部路径和兼容性检查见 [Provider 架构](docs/providers.md)。

## 多平台查询

`platforms`、`api list`、`api show` 和 `api call --dry-run` 完全离线。先查看新版参数，再执行有费用上限的查询：

```bash
uv run soota api call bilibili.web.fetch_one_video \
  --param 'url=https://www.bilibili.com/video/BV1M1421t7hT' --dry-run --json
uv run soota api call bilibili.web.fetch_one_video \
  --param 'url=https://www.bilibili.com/video/BV1M1421t7hT' \
  --max-cost 0.01 --output ./bilibili-detail.json --json
```

此标识当前选择 `fetch_one_video_v3`。新版接口即使改了参数，也按新版契约校验；例如 V3 使用 `url`，不再接受旧版 `bv_id`。复杂查询参数使用 `--params-file`，POST 请求体使用 `--body`，均从 JSON 文件读取。

通用查询覆盖详情、搜索、作品列表、评论、用户资料、热榜、媒体地址及部分分析接口，具体能力以 `api list --platform 平台 --task 类型` 为准。返回的是经过凭据脱敏的平台 JSON；不会自动分页、下载、转写或生成 Markdown。可续跑目录和标准化内容包目前支持 YouTube、Bilibili。

## 频道与 UP 主目录

先做完全离线的预估，再限定范围采集：

```bash
uv run soota catalog "频道或 UP 主 URL" --max-items 100 --max-pages 3 --dry-run --json
uv run soota catalog "频道或 UP 主 URL" --max-items 100 --max-pages 3 --max-cost 0.004 --json
uv run soota jobs resume JOB_ID --max-items 200 --max-pages 6 --max-cost 0.007 --json
uv run soota catalog "频道或 UP 主 URL" --incremental --max-cost 0.004 --json
```

目录采集默认逐次询问付费；可用 `policy set` 明确启用自动付费。`--max-cost`（USD）是可选的额外上限。条数、页数和费用均是整个任务的累计上限；续跑传入的是新总上限，不是追加额度。费用按受控价格快照在每次请求前预留，实际扣费以 TikHub 账单为准；请求失败或中断后，已预留的额度仍保留。

`--incremental` 创建新快照，跳过本机历史目录中已收录的视频；遇到整页都已收录时停止。默认上限是 100 条、10 页。目录只生成视频链接与已有元数据，不自动获取字幕、音频或摘要。使用方法、恢复边界与接口证据见 [目录采集说明](docs/catalog.md)。

## 输出与个人配置

用户配置位于 `~/.config/soota/`，输出默认位于 `~/Documents/Soota/`。可通过 `SOOTA_OUTPUT_DIR` 或 `--output` 指定 Obsidian 内的目录，Soota 不会自动定位或写入知识库。个人路径、账号选择和凭据从环境变量读取，不应把实际值写入项目或共享 Skill。名单、处理规则和采集结果保存在项目外的私人文件中。若知识库使用 Git，同样需要明确排除私人目录；详见[终端教程](docs/terminal-tutorial.md#个人资料与知识库规则)。

```text
output/{platform}/{source_id}/
├── context.md
├── transcript.md
└── manifest.json

output/catalogs/{job_id}/
├── catalog.json
└── catalog.md
```

单条视频有字幕时不下载媒体、不跑 ASR；已缓存的视频阶段再次运行不再付费请求 TikHub。目录新快照会重新读取页面；`jobs resume` 复用已保存的页面和未消费条目。
`context.md` 是给 Agent 的原文输入，保留片段顺序、重复与断句，不做语义处理。`transcript.md` 保留来源时间轴，缺失时明确标记未知。默认不生成文章；分析请求直接使用 context，明确要求详细阅读时才由 Agent 整理文章。`content.md` 是可选的阅读／分析输出，`render` 只负责排版，不调用大模型。统一转换层支持 SRT、VTT、TTML、SRV/XML、已知字幕 JSON、Whisper TSV/JSONL 和无时间 TXT；不同 Provider 共享解析入口。字幕格式能力表、限制及获取优先级见 [字幕格式与 context](docs/subtitle-formats.md)。TikHub 音频失败时回退本机 `yt-dlp`，不循环重试计费接口。

## 质量

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/soota
uv run pytest
```

测试默认不访问真实 TikHub。目录契约测试使用官方 OpenAPI 形状构造的样例；API 与 CLI 集成测试使用真实 SDK 和模拟 HTTP 传输，不能代替真实接口验收。接口注册表随软件打包，更新方式及实现职责见 [TikHub 接口说明](docs/tikhub-api.md)。

## 许可证

Copyright 2026 Soota contributors. Soota 自有代码采用 [Apache-2.0](LICENSE)。第三方组件保留各自许可与版权，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；TikHub 2.1.2 的元数据与许可证正文存在尚未澄清的冲突。
