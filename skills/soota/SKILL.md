---
name: soota
description: Use the local soota CLI to discover and query TikHub content APIs across platforms, ingest YouTube or Bilibili videos, recover captions or ASR, render Markdown bundles, or collect and resume bounded creator catalogs. Use for content details, searches, profiles, comments, transcripts, summaries, and creator lists. Do not use for Obsidian vault routing or for talking to TikHub MCP.
---

# Soota

Use the **Soota CLI** for platform JSON queries or to turn a YouTube/Bilibili URL into `content.md` + `transcript.md` + `manifest.json`. Do not call TikHub directly, scrape pages, or paste API keys.

Project: `/path/to/soota`

```bash
SOOTA=(uv run --project /path/to/soota soota)
# or PATH soota after `uv sync`
```

## Workflow

1. Map intent: platforms / api list / api show / api call / inspect / estimate / ingest / captions-only / asr / summarize / render / catalog / resume. For platform content queries, use **API workflow** below; normalized ingestion currently supports YouTube and Bilibili.
2. Run `soota doctor --json` if the environment is unknown.
3. `soota inspect "URL" --json`. For YouTube channels or Bilibili creators, follow **Catalog workflow** below. YouTube playlists are not supported.
4. Before any paid ingest, run `soota estimate "URL" --mode ingest --json`. Show endpoint count, estimated USD, and `data.wallet`. If `wallet.sufficient` is false or warnings mention 余额不足, stop and tell the user to recharge paid balance. Do not ingest into a 402.
5. Ingest:

```bash
uv run --project /path/to/soota soota ingest "URL" \
  --transcript auto|captions-only|asr|none \
  --json
```

6. For a summary, **read `transcript.md` from disk in chunks**. Never dump the full transcript into the user-visible reply.
7. Write Analysis JSON matching `schemas/analysis.v1.json`, then:

```bash
uv run --project /path/to/soota soota render \
  --bundle "$OUT/manifest.json" --analysis "$OUT/analysis.json" --json
```

8. Report: output paths, transcript source (`official`/`auto`/`asr`/`missing`), cache hit, request count, estimated cost, and failures. `content.md` 的「正文」是无时间戳的可读文本；密集时间轴只在 `transcript.md`。

## API workflow

1. Run `soota platforms --json` to distinguish API discovery from normalized pipelines. The registry currently covers 21 platform/product entries (WeChat has three entries). `live_verified: false` means the whole platform has not passed live acceptance.
2. Discover a query with `soota api list --platform PLATFORM --task detail|profile|catalog|search|comments|media|trends|live|analytics|commerce|utility --json`. Use one task value per command. Check `callable`; helpers and non-content services can be listed but cannot be executed. Follow `next_offset` with `--offset` when needed.
3. Run `soota api show KEY --json`. Use the returned path and request schema. Same-function versions resolve to the highest nondeprecated version in the reviewed registry; old parameter names are not silently translated. Do not downgrade for price.
4. Run `soota api call KEY --param name=value --dry-run --json`. Use `--params-file query.json` for complex query values and `--body body.json` for a POST JSON object, array, or string as specified by the schema. Discovery and dry runs are offline, create no jobs, and need no key. Keep cookies and credentials in local files, not chat or command text.
5. Execute within the user's authorized scope with `soota api call KEY ... --max-cost USD --output NEW_FILE.json --json`. The CLI looks up free pricing metadata, reserves the quoted price before the query, and disables automatic retries. Unknown or excessive prices stop the query. Do not bypass the CLI payment gate: ask mode confirms each paid request; non-TTY pauses with payment_required. Do not enable auto mode without the user selecting that policy.
6. Read the saved JSON or `data.response`. Credentials are redacted; other platform fields remain platform-specific. This command performs one query and does not provide automatic pagination, job resume, caching, ASR, or Markdown rendering. A platform API entry is not evidence that `ingest` supports that platform. Report the selected endpoint, result path, reserved cost and any error; billing remains unknown (`actual_cost_usd: null`).

See `docs/tikhub-api.md` in the project for the platform matrix and version-update workflow. This phase prioritizes breadth and compatibility; retain existing caches and budget controls without choosing older endpoints to reduce cost.

## Catalog workflow

1. Run `soota catalog "URL" --max-items N --max-pages P --dry-run --json`. This is offline and creates no job. `soota estimate "URL" --mode catalog --json` is equivalent with default limits.
2. Use the user's authorized scope and USD cap. Run `soota catalog "URL" --max-items N --max-pages P --max-cost USD --json`. Execution uses the saved payment policy (ask by default); an explicit cap is optional; do not treat permission to list a creator's videos as permission for bulk transcripts or ASR.
3. Read `data.catalog` (`catalog.json`) or `data.content` (`catalog.md`). Catalogs contain links and metadata only. Classification and bulk deep processing remain unimplemented.
4. For a paused task, use `soota jobs resume JOB_ID --max-items N --max-pages P --max-cost USD --json`. All three values are new cumulative limits; prior requests retain their cost reservations. Reuse an existing authorized cap without asking again; obtain authorization before increasing it.
5. For a fresh update, use `soota catalog "URL" --incremental --max-cost USD --json`. It skips IDs from prior local catalogs and stops at a whole page of known items. It does not refresh old metadata or guarantee discovery across a reordered historical feed.
6. Report the job ID, saved paths, item count, `job_status`, `stop_reason`, `reserved_cost_usd`, and any error. `actual_cost_usd` is unknown until reconciled with TikHub billing. Exit 2 means partial output or a paused limit, not full completion.

Only catalog jobs support `jobs resume`; old single-video jobs remain viewable through `jobs list`.

## Hard rules

- One CLI: `soota`. No per-platform MCP.
- API execution uses the saved payment policy; `--max-cost` is an optional additional cap. Failed calls retain their reservation. `--output` must name a new file.
- `--json` stdout is one JSON document. Read `data.transcript` as a path.
- Catalog `--max-items`, `--max-pages`, and the price-snapshot reservation cap `--max-cost` apply across resumes. Unknown prices stop before dispatch. Failed or interrupted calls retain their reservations; do not claim reserved cost is confirmed billing.
- Captions beat ASR. Danmaku/comments/descriptions are not captions.
- Default audio only; never archive full video unless the user explicitly asks.
- If `TIKHUB_API_KEY` is missing, explain env/Keychain setup. Do not ask the user to paste the key in chat.
- Do not download Whisper/faster-whisper models larger than `base` without confirmation.
- Do not write into the Obsidian vault.
- Invalid Analysis must not overwrite a good `content.md`; the CLI already enforces this.

## Analysis JSON

```json
{
  "schema_version": 1,
  "summary": "...",
  "key_points": [{"text": "...", "evidence": ["seg-000001"]}],
  "chapters": [{"title": "...", "start_ms": 0, "end_ms": 12000, "summary": "..."}],
  "tags": ["..."],
  "language": "zh"
}
```

Evidence IDs must exist in `transcript.md`.

## Recover

| Symptom | Action |
|---|---|
| `api_key_present: false` | User sets `TIKHUB_API_KEY` or Keychain `soota.tikhub` / `api_key` |
| exit 4 | Budget/auth or wallet short; show estimate/wallet, do not retry paid calls |
| exit 2 with `catalog_paused` | Inspect `stop_reason`; resume within authorized cumulative limits |
| exit 7 | Repair the local storage/output problem, then resume the catalog job |
| exit 8 | Provider contract drift; stop and show the endpoint |
| `transcript_missing` | Metadata was saved; decide captions-only vs ASR with cost |

## OpenCLI 与费用路由

使用前阅读项目 `docs/terminal-tutorial.md`、`docs/providers.md`、`docs/features.md`。通过 features list/show/call 映射 OpenCLI + TikHub 原生能力；11 个已核实重叠功能默认 OpenCLI 优先，原始输出仍按 Provider 标明。inspect/ingest 默认同样 OpenCLI 优先；省略零预算时按费用策略处理 TikHub 兜底。默认 ask 逐次确认，非终端返回 payment_required；用户明确选择后才能 policy set --mode auto --min-balance USD 或 --no-balance-limit，此时默认 TikHub。max-cost 是可选附加上限，0 禁止计费请求。catalog X 是完整性未知、最多 200 条的最近快照；不能 resume 或宣称历史全量。运行时升级仍隔离安装，不覆盖全局版本或重启不同版本的 daemon。写入命令需显式 --allow-write；不得把执行能力当作已获用户授权。
