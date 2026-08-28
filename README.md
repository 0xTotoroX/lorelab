# Soota

给 Soota 一个链接：搜集内容、清理噪声、补全字幕，留下可追溯的 Markdown。

Soota 是本地优先的内容摄取 CLI。Codex Skill 负责把自然语言变成确定的 `soota` 命令；Soota 不实现 Obsidian 知识管理，也不把 TikHub 按平台拆成多个 MCP。

## 安装

需要 Python 3.12+、ffmpeg。无字幕路径还需要本机 `whisper` CLI（默认模型 `base`）。

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

```bash
uv run soota doctor --json
uv run soota inspect "URL" --json
uv run soota estimate "URL" --mode ingest --json
uv run soota ingest "URL" --transcript auto --output PATH --json
uv run soota render --bundle PATH/manifest.json --analysis analysis.json
uv run soota jobs list --json
```

字幕模式：`auto`、`captions-only`、`asr`、`none`。

`--json` 时 stdout 只有一个 JSON 文档；日志和警告在 stderr。

## 输出

```text
output/{platform}/{source_id}/
├── content.md
├── transcript.md
└── manifest.json
```

有字幕时不下载媒体、不跑 ASR。同一来源第二次运行走缓存，不再付费请求 TikHub。
`content.md` 的「正文」是合并后的可读文本，不含密集时间戳；时间轴只留在 `transcript.md`。TikHub 音频失败时回退本机 `yt-dlp`，不循环重试计费接口。

## 质量

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/soota
uv run pytest
```

真实 TikHub 调用默认关闭。
