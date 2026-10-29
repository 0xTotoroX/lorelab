# cmd/

> L2 | 项目结构：[README.md](../README.md#project-structure)

Cobra commands load configuration and delegate API work to internal/client.
`card batch` uses its own JSON encoder to keep the versioned envelope at the
top level. Other commands retain the existing output/notification helpers.

## 成员清单

- `root.go`: Root flags, Execute, output helpers and update notices.
- `auth.go`: Login, status and logout.
- `card.go`: List, detail, RAG and card mutations.
- `card_batch.go`: Read-only batch flags, ID files, one Client and fixed JSON output.
- `card_batch_test.go`: ID inputs, CLI contract, subprocess exit status and sanitized stderr.
- `folder.go`: Folder listing and web/app mutations.
- `tag.go`: Tag operations.
- `tag_prune.go`: Empty-tag preview and removal command.
- `tag_topic.go`: Topic classification command.
- `tag_topic_batch.go`: Topic collection, review and backfill commands.
- `tag_topic_batch_test.go`: Local topic-plan checks.
- `save.go`: Save and verify cards.
- `update.go`: Update card fields.
- `archive.go`: Archive/unarchive cards and folder resolution.
- `delete.go`: Preview and delete cards, optionally prune affected tags; JSON dry-run lists every requested ID without large-batch detail requests.
- `delete_test.go`: Deletion/pruning checks and actual JSON/text dry-run output contracts.
- `annotation.go`: Annotation listing.
- `marks.go`: Web/app highlight operations.
- `recycle.go`: Recycle-bin operations.
- `lists.go`: Reading-list operations.
- `import.go`: Bookmark import and progress.
- `export.go`: Export requests and readiness.
- `webinfo.go`: Account and insight operations.
- `ai.go`: AI streaming commands.
- `version.go`: Version display.

[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
