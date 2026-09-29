# Soota 目录

Use `soota catalog URL --max-items N --max-pages P --dry-run --json` for an offline scope check, then `catalog ... --max-cost USD --json` when the budget is authorized. X catalog is a recent snapshot with unknown historical completeness; OpenCLI snapshots cannot resume. opencli-mcp is disabled. YouTube channels and Bilibili creators use TikHub pagination and can resume with `soota jobs resume JOB_ID`; limits on resume are cumulative ceilings. `--incremental` creates a new snapshot and deduplicates known IDs. A catalog contains links and existing metadata, not bulk transcripts or summaries.

Read `data.catalog` or `data.content` from disk. Report provider, item count, completeness, job status, saved paths, estimated or reserved cost, and stop reason. `actual_cost_usd: null` means the real bill has not been reconciled. See `docs/catalog.md` for the full command contract.
