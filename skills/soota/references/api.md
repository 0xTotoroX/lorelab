# Soota API 与功能入口

Use existing Soota business commands for supported standardized workflows. For an ad hoc query, follow this discovery order unless the user explicitly selects a Provider:

1. Run `soota mcp search "site task" --json`. Inspect descriptions and `args`. If an appropriate read command exists, create typed JSON parameters and use `soota mcp run SITE COMMAND --params-file params.json --dry-run --json`, then execute with `--output NEW_FILE.json --json`. Discovery and dry-run contact the local MCP host; dry-run does not dispatch the site operation. The CLI rechecks read access and argument types in the same session before execution.
2. If MCP lacks the required capability, inspect `opencli list -f json` and the selected command's `--help`, then invoke OpenCLI directly. Do not invent `soota features call opencli.*` commands: that bulk mapping has been removed. Direct OpenCLI calls have their upstream output and behavior, not Soota's standardized pipeline contract.
3. If those sources cannot supply the capability, use `soota api list/show/call` for TikHub. Read the endpoint schema and preview with `--dry-run` before execution. Retain the payment gate and budget.

The existing `soota features list/show/call` interface retains verified business aliases, three original MCP adapters, and TikHub wrappers. The MCP discovery interface exposes read-only site commands, not arbitrary browser tools. Empty results, authentication failures, rate limits and uncertain outcomes do not establish capability absence or authorize another charge. Do not infer complete history from a bounded result or swap pagination cursors across Providers.

Save large native responses to files and read only what the task needs. For TikHub, use `--params-file` or `--body` for sensitive or complex data. A paid call in ask mode requires an interactive terminal; noninteractive execution returns `payment_required`. `--max-cost 0` forbids billed requests. Never send a key or Cookie through chat.

See `docs/features.md` and `docs/tikhub-api.md` in the project for exact command parameters and endpoint versions.
