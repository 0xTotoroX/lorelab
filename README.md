# Soota

给 Soota 一个链接：搜集内容、清理噪声、补全字幕，留下可追溯的 Markdown。

Soota 是本地优先的内容摄取 CLI：通过独立 Provider 优先使用 OpenCLI 的已验证免费能力，并查询 TikHub 各平台内容，并为 YouTube、Bilibili 提供字幕、ASR 和 Markdown 流程。Codex Skill 负责把自然语言变成确定的 `soota` 命令；Soota 不实现 Obsidian 知识管理，也不把 TikHub 按平台拆成多个 MCP。

已接入 OpenCLI 的 X 最近快照与视频元数据，提供零预算控制、显式元数据兜底及独立运行时升级/回滚。详见 [终端参考教程](docs/terminal-tutorial.md) 和 [Provider 架构](docs/providers.md)。同功能存在多个版本时使用最高的未废弃版本，不因旧版本便宜而降级。接口版本和平台能力清单见 [TikHub 接口说明](docs/tikhub-api.md)。

## 安装

需要 Python 3.12+。音频处理需要 ffmpeg；无字幕转写路径还需要本机 `whisper` CLI（默认模型 `base`）。纯 API 查询不需要这些音频工具。

```bash
cd /path/to/soota
uv sync --extra dev
uv run soota doctor --json
```

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

字幕模式：`auto`、`captions-only`、`asr`、`none`。

`--json` 时 stdout 只有一个 JSON 文档；日志和警告在 stderr。

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

执行目录采集必须提供 `--max-cost`（USD）。条数、页数和费用均是整个任务的累计上限；续跑传入的是新总上限，不是追加额度。费用按受控价格快照在每次请求前预留，实际扣费以 TikHub 账单为准；请求失败或中断后，已预留的额度仍保留。

`--incremental` 创建新快照，跳过本机历史目录中已收录的视频；遇到整页都已收录时停止。默认上限是 100 条、10 页。目录只生成视频链接与已有元数据，不自动获取字幕、音频或摘要。使用方法、恢复边界与接口证据见 [目录采集说明](docs/catalog.md)。

## 输出

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
