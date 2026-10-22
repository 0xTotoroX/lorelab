---
name: soota
description: Use the local Soota CLI to collect content, download media and subtitles, transcribe files, or export bundles. Also use for requested knowledge extraction from pasted text or Cubox batches, with optional Mubu outline delivery. Save unprocessed context by default; analysis and destination writes require a request. Ordinary explanations do not require collection.
---

# Soota

Use an installed `soota` command. For a source checkout, resolve this SKILL.md symlink, locate the repository two directories above its skill directory, verify pyproject.toml belongs to Soota, and run `uv run --project <repository> soota ...`. Do not hard-code a personal checkout path. Codex calls this CLI; Soota chooses its internal Providers. Do not register opencli-mcp as a separate Codex tool for this workflow.

## Choose the requested output

Use `ingest INPUT --want ... --json` for explicit artifacts and combinations: `video`, `audio`, `transcript`, `context`, `markdown`, `images`, `data`, `analysis`, `note`, `outline`, `article`. `--optional` declares outputs whose failure does not block the required ones. Inputs can be URLs, local files, a bundle directory or manifest, and `--inputs-file` lists. For batch processing, existing bundles, explicit native operations, analysis handoffs or exports, read [task workflow](references/tasks.md).

Unified tasks accept `--workers 1..8` (default 1). Start with the requested bound, or a small bound such as 2 for an authorized batch; enumeration and result ordering remain stable. Resume retains the saved bound unless overridden. All workers share one durable budget; increasing concurrency does not increase the cap. Ctrl-C drains started workers before releasing the job lock, so shutdown can take until provider timeouts.

Default collection ends at unprocessed context. Saving an existing article uses `context` or `markdown`; `article` requests a separate reading article written by the Agent. Do not introduce an article step before a summary or analysis. A media-only request does not authorize transcription or summarization; do not load the full body for a download-only request.

For “save this pasted text to my knowledge base”, read [concise knowledge workflow](references/knowledge.md). Preserve the paste as a local text file, use `--provider local --want context,note`, and let the Agent split, deduplicate and classify the requested knowledge using the destination's current rules and prompt. A paste containing URLs is still supplied text; do not turn it into link collection. A summary-only request does not authorize knowledge-base writes.

For a requested Cubox → knowledge/Mubu batch, use the same [knowledge workflow](references/knowledge.md#cubox-batches-and-source-snapshots). Reuse Cubox CLI `card batch`, preserve actual source text and provenance locally, then ingest the source-file list with `--want context,note,outline`. `body_available` is not proof of full original content; supplement missing material through Soota's existing acquisition paths. Topic Agents prepare isolated drafts; one writer merges knowledge and serializes Mubu CLI `node-import` plus readback. Do not implement either service's private API or embed personal paths, deletion rules or prompts.

The existing single-video command without `--want` remains available: `ingest URL --transcript captions-only|auto|asr|none --json`. Use `inspect URL --json` for metadata only. Use `doctor --json` when required runtimes are unknown.

## Acquisition and failures

Video captions follow saved platform/capability cost or manual priorities. Free sources precede paid sources by default; optional Monid uses Apify for YouTube captions and TikHub relay for supported contracts. Use `providers auth/enable/disable` and `providers priority set/show`; quote full request chains, not unrelated endpoint prices. Read [provider configuration](references/providers.md) for CLI examples. Confirmed missing tracks end the caption chain: `auto` obtains audio and transcribes locally, while `captions-only` stops without ASR. Empty responses, unknown states and login failures are not proof of absent captions. `asr` explicitly requests transcription. Missing timestamps stay unknown; do not invent timed exports or apply timed filtering to untimed text.

Comments and danmaku are not captions. Bilibili `ai-*` tracks are automatic subtitles, acquired with ordinary subtitle flags. Legacy `--provider soota` remains a yt-dlp alias; new results identify `yt-dlp`.

`--provider` selects the source strictly; common local conversion and verification do not change that source. For ASR audio, `--audio-provider yt-dlp` is the default, `downie` is opt-in on macOS and needs the completion hook, and `tikhub`/`monid` require payment authorization. `--audio-provider auto` uses the audio priority rule. Empty subtitle results can still be billed; Monid receipts record upstream, runId and reported actual cost. Resume pending runs without a second submit; never erase a task reservation to retry. TikHub audio failure does not authorize a new yt-dlp acquisition. A `download_pending` result is unfinished: inspect the original task and resume without resubmitting a Downie download.

`--max-cost 0` blocks billed requests. Unified batch jobs share durable reservations, including enumeration and later audio requests; resume does not reset them. In ask mode, noninteractive paid calls stop with `payment_required`. Do not bypass that gate or enable automatic payment for the user. Login, permission, rate-limit, timeout and contract errors do not authorize blind retries or manual paid fallback.

MCP is disabled by default; do not enable, discover or start it for an ordinary task. `capabilities --json` inspects local capabilities without querying websites or checking login. Distinguish discovered/native/standard capabilities from actual site and artifact verification. A listed command does not imply standard content, media or collection support. For broader API queries, read [API reference](references/api.md); for catalog pagination and incremental snapshots, read [catalog reference](references/catalog.md).

## Optional subtitle selection

For requested Bilibili → YouTube counterpart selection, use `--prefer-youtube`; `--no-prefer-youtube` disables it. This requires same-author and same-episode evidence. Do not claim verified creator identity when `author_crosslink_confirmed` is false. Read `selection` / `youtube_check` for the actual choice.

This option also enables promotion filtering; `--keep-promotions` overrides it. `--exclude-range START_SECONDS:END_SECONDS` removes independently reviewed intervals, retaining original times and stable segment IDs. Review unannotated ads when the user asks for promotion-free output; absent annotations do not prove absence. Changed filtering may require a new output folder or authorized source replacement. See `docs/subtitle-selection.md` for current restrictions.

## Results and analysis

`--json` prints one status document. For unified jobs, inspect `job_status`, `items`, each item's missing outputs, errors and artifact paths, plus enumeration completeness and reserved cost. Report actual files and Providers; successful enumeration or one completed step does not mean every requested artifact is complete. A passed file hash does not establish full-length media when source duration is unknown.

Read `data.context` or the item's context path as the Agent input. `transcript.md` retains timestamped evidence; v2 body blocks provide paragraph IDs. Old bundles without context can use `transcript.md`. The legacy ingest `data.content` remains a compatibility alias for context. `source_preserved` means the current attempt did not replace an existing valid source; do not call it fresh acquisition.

For `waiting_analysis`, read the task's actual `analysis-request.json`, context and applicable user prompt, produce the requested submission, then run `jobs resume --analysis`. Preserve task/item identity and the current context fingerprint; use only existing evidence IDs. Do not mark the task complete merely because a handoff file exists. Detailed new-task submission instructions are in [task workflow](references/tasks.md); [analysis guidance](references/analysis.md) covers source-grounded writing and the legacy v1 render path. Stale/pending metadata alone does not authorize generating unrequested analysis or an article.

## Destinations and local rules

Before writing to a user-selected collection, read its applicable `AGENTS.md` and only the referenced rules or prompts relevant to this task. Honor the allowed-source list and existing classification. CLI export does not interpret these rules or choose a knowledge category. Use explicit `--destination` or `--vault`/`--subdir`; never guess a private vault path. Export conflicts preserve handwritten files and need a new destination or a user decision about those files, not an automatic force overwrite.

Use collection display names for reading labels; preserve CLI-managed bundle paths, source IDs and manifest fields unless the task explicitly includes a compatible migration.

Keep personal paths, browser choices, credentials, creator lists and prompts in user-owned configuration or collection files. Supported environment variables include `SOOTA_OUTPUT_DIR`, `OPENCLI_PROFILE`, `SOOTA_YTDLP_BINARY`, `SOOTA_YTDLP_COOKIES_BROWSER`, and `TIKHUB_API_KEY`; never embed actual values in the Skill or project. Do not put cookies or keys in chat or command arguments. Project-external files can still be synced or Git-tracked; check the destination's own rules. Soota does not automatically manage watchlists, schedule collection or reorganize a knowledge base.

Online collection/API commands update published provider packages by default; inspect `runtime_updates` and warnings. Help, offline plans, local processing, analysis submission and render do not need a website update check. `updates check` is read-only; `updates apply` is an explicit update. Updating MCP does not enable it. `SOOTA_AUTO_UPDATE=false` preserves a pinned runtime. yt-dlp and Downie are updated separately. Package availability and compatibility checks do not prove a website works.
