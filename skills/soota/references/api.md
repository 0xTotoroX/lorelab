# Soota API 与功能入口

Use `soota features list/show/call` for the verified union of opencli-mcp, OpenCLI, and TikHub. Native `opencli-mcp.*` entries are a small read-only allowlist; the full MCP browser toolset stays internal. `soota api list/show/call` accesses TikHub directly. Read `show` or run `--dry-run` before a new operation. `features call ... --output NEW_FILE.json --json` saves a redacted native response and keeps large payloads off stdout. Outputs from different Providers retain their own schemas.

TikHub queries still pass the CLI payment gate and budget. Use `api call KEY --param name=value --dry-run --json` to check the request; use `--params-file` or `--body` for sensitive or complex data. A paid call in ask mode requires an interactive terminal; noninteractive execution returns `payment_required`. `--max-cost 0` forbids billed requests. Never send a key or Cookie through chat.

See the project's `docs/features.md` and `docs/tikhub-api.md` when exact command parameters or endpoint versions matter.
