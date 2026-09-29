# Soota

给 Soota 一个链接：搜集内容、清理噪声、补全字幕，留下可追溯的 Markdown。

Soota 是本地优先的内容摄取 CLI：优先使用 OpenCLI 的已核验免费能力，再按费用策略使用 TikHub，并为 YouTube、Bilibili 提供字幕、ASR 和 Markdown 流程。Codex Skill 把自然语言任务变成 `soota` 命令。opencli-mcp 当前默认停用，不参与自动路由。

已接入 OpenCLI 的 X 最近快照、Bilibili 和 YouTube 视频元数据及字幕；还提供可选的 B站同作者同一期 YouTube 字幕优先、推广片段过滤、11 个统一业务入口、TikHub 接口封装、逐次确认/自动付费策略，以及 OpenCLI 的独立升级/回滚。完整命令见 [功能映射与费用策略](docs/features.md)、[终端参考教程](docs/terminal-tutorial.md) 和 [Provider 架构](docs/providers.md)。接口版本和平台能力清单见 [TikHub 接口说明](docs/tikhub-api.md)。

## 安装

需要 Python 3.12+。音频处理需要 ffmpeg；无字幕转写路径还需要本机 `whisper` CLI（默认模型 `base`）。纯 API 查询不需要这些音频工具。

```bash
cd /path/to/soota
uv sync --extra dev
uv run soota doctor --json
```

OpenCLI 需要 Node.js、Chrome 和 Browser Bridge 扩展。可用 `uv run soota runtime update --json` 安装最新稳定运行时，再用 `uv run soota runtime connect --json` 启动所选版本并等待扩展连接。无需安装 opencli-mcp。

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
├── content.md
├── transcript.md
└── manifest.json

output/catalogs/{job_id}/
├── catalog.json
└── catalog.md
```

单条视频有字幕时不下载媒体、不跑 ASR；已缓存的视频阶段再次运行不再付费请求 TikHub。目录新快照会重新读取页面；`jobs resume` 复用已保存的页面和未消费条目。
`content.md` 的「正文」是合并后的可读文本，不含密集时间戳；时间轴只留在 `transcript.md`。TikHub 音频失败时回退本机 `yt-dlp`，不循环重试计费接口。

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
