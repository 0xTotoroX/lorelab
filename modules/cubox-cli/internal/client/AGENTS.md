# internal/client/

> L2 | 项目结构：[README.md](../../README.md#project-structure)

Client owns HTTP transport and a shared 500 ms request-admission clock. Batch
reads reuse that Client, validate detail IDs, and maintain their own latched
three-error stop over complete outcomes. Legacy detail semantics stay unchanged.

## 成员清单

- `client.go`: Client transport, authentication styles, API operations, shared throttle.
- `types.go`: Existing API payload types, including the unchanged CardDetail.
- `card_batch.go`: GetCardBatch, versioned result/error/count types, bounded workers and batch stop.
- `card_content.go`: ClassifyCardContent; local Markdown evidence only, no completeness claim or network access.
- `card_batch_test.go`: Concurrency, throttle, stop, identity, redirection, sanitization and compatibility checks.
- `card_content_test.go`: Empty/link/login/description/body classification with synthetic fixtures.

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
