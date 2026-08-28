---
name: soota
description: Ingest a YouTube or Bilibili URL with the local soota CLI, recover captions or ASR, and render a Markdown content bundle. Use when the user drops a video link and wants a transcript, summary, or Soota content pack. Do not use for Obsidian vault routing or for talking to TikHub MCP.
---

# Soota

Turn a YouTube/Bilibili URL into `content.md` + `transcript.md` + `manifest.json` by calling the **Soota CLI**. Do not call TikHub, scrape pages, or paste API keys.

Project: `/path/to/soota`

```bash
SOOTA=(uv run --project /path/to/soota soota)
# or PATH soota after `uv sync`
```

## Workflow

1. Map intent: inspect / estimate / ingest / captions-only / asr / summarize / render.
2. Run `soota doctor --json` if the environment is unknown.
3. `soota inspect "URL" --json`. Channel/playlist/catalog is out of scope (M5).
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

## Hard rules

- One CLI: `soota`. No per-platform MCP.
- `--json` stdout is one JSON document. Read `data.transcript` as a path.
- `--max-cost` and `--max-items` are hard limits.
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
| exit 8 | Provider contract drift; stop and show the endpoint |
| `transcript_missing` | Metadata was saved; decide captions-only vs ASR with cost |
