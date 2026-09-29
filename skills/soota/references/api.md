# Soota API 与功能入口

Use existing Soota business commands for supported standardized workflows. For an ad hoc query, follow this discovery order unless the user explicitly selects a Provider:

1. Inspect `opencli list -f json` and the selected command's `--help`, then invoke OpenCLI directly. Do not invent `soota features call opencli.*` commands: that bulk mapping has been removed. Direct OpenCLI calls have upstream output and behavior, not Soota's standardized pipeline contract.
2. For YouTube single-video metadata/captions, use `soota inspect/ingest --provider soota --max-cost 0`; the built-in provider runs yt-dlp. The `youtube.video.detail` alias also supports it.
3. If neither free provider supplies the capability, use `soota api list/show/call` for TikHub. Read the endpoint schema and preview with `--dry-run` before execution. Retain the payment gate and budget.

opencli-mcp is disabled, including `mcp search/run`; do not attempt it during ordinary work. The existing `soota features list/show/call` interface retains 11 verified business aliases and TikHub wrappers. Empty results, authentication failures, rate limits and uncertain outcomes do not establish capability absence or authorize another charge. Do not infer complete history from a bounded result or swap pagination cursors across Providers.

Save large native responses to files and read only what the task needs. For TikHub, use `--params-file` or `--body` for sensitive or complex data. A paid call in ask mode requires an interactive terminal; noninteractive execution returns `payment_required`. `--max-cost 0` forbids billed requests. Never send a key or Cookie through chat.

See `docs/features.md` and `docs/tikhub-api.md` in the project for exact command parameters and endpoint versions.
