# cubox-cli

[License: MIT](https://opensource.org/licenses/MIT)
[Go Version](https://go.dev/)

[English](./README.md) | [中文版](./README.zh.md)

The LoreLab-maintained Cubox CLI fork. Save, search, read, and use what you read with AI. Your personal reading memory, now usable.

[Install](#installation) · [Auth](#authentication) · [Commands](#commands) · [AI Agent](#quick-start-ai-agent) · [Examples](#examples) · [Development](#development)

## ⭐ Fork Addition: What This Fork Adds Over the Official CLI

> This component is maintained in LoreLab. Installation and updates use the bundled source and Skill, not the original author's releases.

Compared with the official CLI (v1.0.10), this fork **unlocks the full web/app API group** that the official CLI does not expose:

| Area | Official CLI | This Fork |
| ---- | ------------ | --------- |
| Folders | `list` only | + **delete** (safe mode), **new** (nested paths), **rename**, **archive**, **move** (incl. root level) |
| Recycle bin | ✗ | + `recycle list / recover / clean` |
| Marks (highlights) | ✗ | + `mark list / count / delete / color / export` |
| Reading lists | ✗ | + `lists` full CRUD, item management, publish, sort, check |
| Batch card ops | single-card only | + batch `star / read / move / tag` |
| Tags | ✗ new | + `tag new`, `tag sort` |
| Export | ✗ | + `export status / bookmarks / mail` |
| Import | ✗ | + `import bookmarks --file` (official task pipeline, no 20-item truncation) |
| Account | ✗ | + `account apikey / settings / sync / mail / insight / insight-state / more-qas` |
| AI | ✗ | + `ai generate` (SSE streaming), `ai ask` (experimental, Pro+AI) |
| `save` | basic | + `--skip-existing` dedup, `--verify` audit, nested `--folder`, batched ≤20/req |

**Safety built in** (after a real incident): system-group guard ("未分类" is undeletable), global 500ms request throttle, 3-error circuit breaker, safe-delete + `--dry-run`.

Details and reverse-engineering notes: see [FORK.md](./FORK.md).

---

## Features


| Category | Capabilities                                                                          |
| -------- | ------------------------------------------------------------------------------------- |
| Folders  | List and browse card folders                                                      |
| Tags     | List and browse tag hierarchy; rename, batch delete, and merge tags                   |
| Cards    | Filter/search cards by folder, tag, starred/read/annotated/archived status, keyword, exact URL, time range |
| RAG      | Semantic search via natural language query (intent-based retrieval)                    |
| Content  | Read full card detail with article content (markdown), annotations, and AI insight    |
| Save     | Save web pages with optional title/description, batch via JSON            |
| Update   | Star/unstar, mark read/unread, move to folder, manage tags                            |
| Archive  | Batch archive cards or restore (unarchive) them into a folder                         |
| Delete   | Delete cards by ID, with dry-run preview support                             |
| Annotations | List and search annotations across all cards                                      |


## Installation

### Requirements

- LoreLab release installation: use the product installer; no separate Node.js or Go installation is needed.
- Independent source build: Go 1.23+; Node.js 16+ only when using the local npm wrapper.

### Quick Start (Human Users)

> **For AI Agents:** jump to [Quick Start (AI Agent)](#quick-start-ai-agent) below.

#### Install

Use the LoreLab product installer for the matched CLI and Skill. To install an independently exported component instead:

```bash
cd /path/to/exported-cubox-cli
make install
```

Alternatively, `npm install -g .` in that same directory builds the included Go source. Register the complete `skills/cubox` directory in your Agent's Skill directory; do not copy only `SKILL.md`. This private source package is not the public npm package.

#### Log in

```bash
cubox-cli auth login
```

The CLI will guide you through:

1. **Sign in to Cubox web** associated with your account:
   - For .pro users: [https://cubox.pro/web/settings/extensions](https://cubox.pro/web/settings/extensions)
   - For international .cc users: [https://cubox.cc/web/settings/extensions](https://cubox.cc/web/settings/extensions)
2. **Enable the API Extension** — go to Extensions, locate the API Extension, enable it, and copy your unique link (e.g. `https://cubox.pro/c/api/save/abcd12345`).
3. **Paste the link** — the CLI extracts the token and server automatically.

#### Start using

```bash
# List your folders
cubox-cli folder list

# List your tags
cubox-cli tag list

# Browse recent cards
cubox-cli card list --limit 5 -o pretty

# Read an article
cubox-cli card detail --id CARD_ID
```

### Quick Start (AI Agent)

> These steps are for AI Agents helping users set up cubox-cli.

**Step 1 — Install**

Use LoreLab's installer and `lorelab skills list`, or follow the independent source installation above. Keep the CLI and complete Skill from the same exported version.

**Step 2 — Authenticate**

Ask the user to sign in to their Cubox web and get the API link:

1. Please sign in to the Cubox web associated with your account:
   - For .pro users: `https://cubox.pro/web/settings/extensions`
   - For international .cc users: `https://cubox.cc/web/settings/extensions`
2. Go to Extensions, locate the API Extension, enable it, and copy your unique link (e.g., `https://cubox.pro/c/api/save/abcd12345`).

The agent **must not** ask the user to paste the token into chat or embed it into argv. Instead, direct the user to run one of these themselves in their terminal:

```bash
# Interactive (recommended for humans)
cubox-cli auth login

# Agent / CI without persistence — token lives only in the shell environment
export CUBOX_SERVER=cubox.pro
export CUBOX_TOKEN=... # or the full API link URL
cubox-cli folder list

# Non-interactive persisted login — token piped via stdin, never in argv/ps/history
printf '%s' "$TOKEN" | cubox-cli auth login --server cubox.pro --token-stdin
```

The legacy `--token TOKEN` flag still works but exposes the token to shell history and `ps`; only use it in controlled environments.

**Step 3 — Verify**

```bash
cubox-cli auth status
```

**Step 4 — Use**

```bash
cubox-cli folder list
cubox-cli card list --limit 10
```

## Authentication


| Command                                                              | Description                                                              |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `cubox-cli auth login`                                               | Interactive login (server selection + token input)                       |
| `printf '%s' "$TOKEN" \| cubox-cli auth login --server cubox.pro --token-stdin` | Non-interactive login via stdin (recommended for agents)       |
| `CUBOX_SERVER=cubox.pro CUBOX_TOKEN=... cubox-cli ...`               | Transient env-var auth (no file written; recommended for CI / sandboxes) |
| `cubox-cli auth login --server cubox.pro --token TOKEN`              | Legacy argv form — leaks to shell history/ps, avoid when possible        |
| `cubox-cli auth status`                                              | Show current server, masked token, connection test                       |
| `cubox-cli auth logout`                                              | Remove saved credentials                                                 |


Credentials are stored at `~/.config/cubox-cli/config.json`. `CUBOX_TOKEN` and `CUBOX_SERVER` override the on-disk config when set, and are enough on their own when no config file exists.

## Commands

### Output Formats

All commands accept the `-o` / `--output` flag. Most data-oriented commands honor it:


| Flag        | Description                            |
| ----------- | -------------------------------------- |
| `-o json`   | Compact JSON (default, agent-friendly) |
| `-o pretty` | Indented JSON                          |
| `-o text`   | Human-readable text/tree output        |


Note: `save`, `update`, and several `auth` success paths currently print plain text even when `-o json` is selected.

### `cubox-cli version`

Show the installed CLI version.

```bash
cubox-cli version
```

### `cubox-cli folder list`

List all folders.

```bash
cubox-cli folder list
cubox-cli folder list -o text
```

**JSON output fields:** `id`, `nested_name`, `name`, `parent_id`, `uncategorized`

### `cubox-cli tag list`

List all tags.

```bash
cubox-cli tag list
cubox-cli tag list -o text
```

**JSON output fields:** `id`, `nested_name`, `name`, `parent_id`

### `cubox-cli tag update`

Rename a tag by ID. The new name applies to the leaf segment only — nested children stay attached and reachable through the new path automatically.

```bash
cubox-cli tag update --id TAG_ID --new-name NEW_NAME
```

| Flag                | Description                                          |
| ------------------- | ---------------------------------------------------- |
| `--id ID`           | Tag ID to rename (required)                          |
| `--new-name NAME`   | New leaf name (required; must not contain `/`)       |

### `cubox-cli tag move`

Move an existing tag under another tag, retaining its ID and card associations. The command checks the destination, name collisions and parent cycles, then verifies the new parent.

```bash
cubox-cli tag move --id TAG_ID --parent PARENT_TAG_ID
```

Both flags take IDs from `tag list` and are required. This fork command uses the Cubox app login credential, like the other web/app commands.

### `cubox-cli tag topic`

Classify a card from its parsed article content and rank 0–3 topics by centrality. Existing direct children of `主题` form the reviewed vocabulary; the model proposes new concepts from content for later review. Selected approved topics and new suggestions total at most three. Folder paths are context, not a second tag hierarchy.

```bash
export CUBOX_TOPIC_API_URL=https://your-model-service/v1/chat/completions
export CUBOX_TOPIC_MODEL=your-model
# Also set CUBOX_TOPIC_API_KEY locally for a remote model service.

cubox-cli tag topic --id CARD_ID          # preview only
cubox-cli tag topic --id CARD_ID --apply  # append missing approved topics
```

If article parsing fails, the command uses a substantial description and allows at most one topic; title-only or thin content is left untagged. `--apply` rechecks the vocabulary and card before writing, then verifies the result. It preserves existing tags and folders. The card's content and description are sent to the configured model endpoint; preview is the default.

For a batch, collect candidates into a local plan, review every candidate, create only the approved topic tags, then preview and apply the backfill:

```bash
cubox-cli tag topic collect --id CARD1,CARD2 --out topic-plan.json
cubox-cli tag topic review --plan topic-plan.json --name MCP --decision approved
cubox-cli tag topic review --plan topic-plan.json --name "MCP tools" --decision merged --target MCP
cubox-cli tag topic review --plan topic-plan.json --name "too broad" --decision rejected
cubox-cli tag new --name 主题                  # if the root does not exist
cubox-cli tag new --name MCP --parent ROOT_ID # create reviewed new terms only
cubox-cli tag topic backfill --plan topic-plan.json          # preview
cubox-cli tag topic backfill --plan topic-plan.json --apply  # append tags
```

`collect` and `review` never change Cubox. Backfill requires every candidate reviewed and every approved or merged target present under `主题`. It reclassifies current card content rather than replaying old per-card suggestions. Reviewed aliases point to their canonical topic and rejected names are filtered from later suggestions. The local plan does not store the full article body, but it contains card titles, IDs, and model reasons that may quote the article. Batch writes are not transactional: on failure, earlier successful card updates remain. The CLI reports the number of verified updates and warns that the failing card may also have changed.

Optional automatic review keeps the same local plan:

```bash
cubox-cli tag topic collect --id CARD1,CARD2 --out topic-plan.json
cubox-cli tag topic auto-review --plan topic-plan.json
cubox-cli tag topic backfill --plan topic-plan.json --auto          # preview
cubox-cli tag topic backfill --plan topic-plan.json --auto --apply  # create approved tags and append them
```

`auto-review` maps strict synonyms to existing reviewed topics first. A new canonical topic is auto-approved only when the model confirms support in substantial article bodies on at least two distinct cards. Singletons, description-only evidence, and uncertain candidates remain pending in the plan. Synonyms within one card can still be merged into one pending candidate; merging alone does not approve it. Preview uses temporary tag IDs and never changes Cubox. `--auto --apply` creates missing approved `主题` tags using the Cubox app credential, then reclassifies current content and appends topics while preserving existing tags and folders. Tag creation and batch backfill are not transactional; inspect `created`, `applied`, and any error after a partial failure. The model sees article excerpts during synonym review; real semantic quality requires validation with the configured model.

### `cubox-cli tag delete`

Batch delete one or more tags by ID. Cards previously tagged with the deleted tag(s) remain; only the tag-card association is removed.

```bash
cubox-cli tag delete --id TAG_ID[,ID2,...]
```

### `cubox-cli tag prune-empty`

Inspect an already-empty tag by exact name or ID. Preview is the default; `--apply` rechecks and deletes it only if it has no active cards, archived cards, or child tags. The root tags `来源`, `处理`, `skill`, `笔记`, and `主题` are protected.

```bash
cubox-cli tag prune-empty --name PICSED
cubox-cli tag prune-empty --name PICSED --apply
```

After a CLI card deletion, only tags used by those deleted cards are checked and empty leaf tags are pruned automatically. Reviewed `主题/*` vocabulary and `处理/*` workflow tags are retained. Deleting cards in the Cubox app does not invoke the CLI; use this command for tags already emptied there.

| Flag          | Description                                          |
| ------------- | ---------------------------------------------------- |
| `--id ID,...` | Tag IDs to delete (comma-separated, required)        |

### `cubox-cli tag merge`

Merge one or more source tags into a target tag. All cards associated with the source tags are re-tagged onto the target, and the source tags are then deleted.

```bash
cubox-cli tag merge --source SRC_ID[,ID2,...] --target TARGET_ID
```

| Flag              | Description                                          |
| ----------------- | ---------------------------------------------------- |
| `--source ID,...` | Source tag IDs to merge (comma-separated, required)  |
| `--target ID`     | Target tag ID to merge into (required)               |

### `cubox-cli card list`

Filter and search cards. Supports keyword search and exact URL lookup with page-based pagination, and cursor-based pagination for browsing.

```bash
cubox-cli card list [flags]
```


| Flag                | Description                                                        |
| ------------------- | ------------------------------------------------------------------ |
| `--folder ID,...`   | Filter by folder IDs                                               |
| `--tag ID,...`      | Filter by tag IDs                                                  |
| `--starred`         | Only starred cards                                                 |
| `--read`            | Only read cards                                                    |
| `--unread`          | Only unread cards                                                  |
| `--annotated`       | Only cards with annotations                                        |
| `--archived`        | Only archived cards (default: non-archived only)                   |
| `--keyword TEXT`    | Search by keyword                                                  |
| `--url URL`         | Filter by exact card URL                                           |
| `--start-time TIME` | Filter by create time start (e.g. `2026-01-01T00:00:00:000+08:00`) |
| `--end-time TIME`   | Filter by create time end                                          |
| `--limit N`         | Page size (default 50)                                             |
| `--last-id CARD_ID` | Cursor pagination for browsing (non-search)                        |
| `--page N`          | Page number for search (1-based, used with `--keyword` or `--url`) |
| `--all`             | Auto-paginate to fetch all results                                 |


**Pagination:** When `--keyword` or `--url` is set, use `--page` for pagination. Otherwise, use `--last-id` with the last card's ID.

### `cubox-cli card detail --id ID`

Get full card detail including article content (markdown), author, annotations, and AI-generated insight (summary + Q&A).

```bash
cubox-cli card detail --id 7247925101516031380
cubox-cli card detail --id 7247925101516031380 -o pretty
```

Use `-o text` to output only the markdown content.

### `cubox-cli card batch` (fork)

```bash
cubox-cli card batch --id CARD1,CARD2 --workers 2
cubox-cli card batch --ids-file card-ids.txt -o pretty
```

Read multiple details using one Client, a shared 500 ms throttle, and 1..4 workers
(default 2). IDs are deduplicated in first-seen order; `--id` entries precede file
entries (one ID per line). Stdout is always a top-level `cubox_card_batch` JSON
document with `schema_version: 1`, ordered `items`, and `counts`, including with
`-o text`. Partial failure still writes JSON, then exits 1. Three consecutive
completed errors stop new requests while retaining in-flight results and skipped
reasons. `body_available` indicates saved text, never original-post completeness.
No mutations, retries, redirects, or source-site fetches are performed.

See the [batch JSON contract and content limits](skills/cubox/references/card-batch.md).

### `cubox-cli card rag --query TEXT`

Semantic search using natural language via RAG (Retrieval-Augmented Generation). Unlike keyword search, RAG understands intent and returns conceptually relevant cards even when exact words don't match.

```bash
cubox-cli card rag --query "Java实现数据库图片上传功能"
cubox-cli card rag --query "how to build a REST API with authentication" -o pretty
```

| Flag            | Description                            |
| --------------- | -------------------------------------- |
| `--query TEXT`  | Natural language query text (required) |

**When to use RAG vs keyword vs URL:**

- **`card list --url`** — look up a card by its exact stored URL
- **`card list --keyword`** — exact terms, known titles, domain names, short phrases
- **`card rag --query`** — questions, topic exploration, conceptual or fuzzy queries

### `cubox-cli save`

Save one or more web pages as bookmarks. Supports three input modes.

```bash
# Simple — URL arguments
cubox-cli save https://example.com
cubox-cli save https://a.com https://b.com --folder "Reading List"

# Single with metadata
cubox-cli save https://example.com --title "My Page" --desc "Interesting read"

# Batch via JSON
cubox-cli save --json '[{"url":"https://a.com","title":"Title A"},{"url":"https://b.com"}]' --tag tech,AI/LLM
```

| Flag             | Description                                                         |
| ---------------- | ------------------------------------------------------------------- |
| `--title TEXT`   | Title for the saved page (single URL mode only)                     |
| `--desc TEXT`    | Description for the saved page (single URL mode only)               |
| `--json JSON`    | Batch card entries as JSON array `[{"url","title","description"}]`   |
| `--folder NAME`  | Target folder by name (e.g. `"parent/child"`)                       |
| `--tag NAME,...` | Tag names (comma-separated, supports nested like `"parent/child"`)  |

### `cubox-cli update`

Update a card's properties.

```bash
cubox-cli update --id CARD_ID [flags]
```


| Flag                   | Description                                                            |
| ---------------------- | ---------------------------------------------------------------------- |
| `--star` / `--unstar`  | Toggle star                                                            |
| `--read` / `--unread`  | Toggle read status                                                     |
| `--folder NAME`        | Move to folder by name (e.g. `"parent/child"`; `""` = Uncategorized)   |
| `--tag NAME,...`       | Replace all tags by name (comma-separated, supports nested like `"parent/child"`) |
| `--add-tag NAME,...`   | Add tags without removing existing ones                                |
| `--remove-tag NAME,...`| Remove specific tags only                                              |
| `--title TEXT`         | Update title                                                           |
| `--description TEXT`   | Update description                                                     |

> Archive / unarchive are batch operations and live in their own commands — see [`cubox-cli archive`](#cubox-cli-archive) below.

### `cubox-cli archive`

Archive one or more cards by ID. Archived cards are hidden from the default `card list` (use `card list --archived` to view them).

```bash
cubox-cli archive --id CARD_ID[,ID2,...]
```

| Flag          | Description                                              |
| ------------- | -------------------------------------------------------- |
| `--id ID,...` | Card IDs to archive (comma-separated, required)          |

### `cubox-cli unarchive`

Restore one or more archived cards by moving them into a non-archived folder. The destination folder is required.

```bash
cubox-cli unarchive --id CARD_ID[,ID2,...] --folder NAME
```

| Flag             | Description                                                                |
| ---------------- | -------------------------------------------------------------------------- |
| `--id ID,...`    | Card IDs to unarchive (comma-separated, required)                          |
| `--folder NAME`  | Destination folder by name (required; `""` = Uncategorized; `"parent/child"` for nested) |

The folder name is resolved client-side via `folder list`; if the name does not match an existing folder the command fails with a helpful error.

### `cubox-cli delete`

Delete one or more cards by ID. Supports `--dry-run` to preview what would be deleted before committing.

```bash
cubox-cli delete --id CARD_ID [flags]
```


| Flag            | Description                                            |
| --------------- | ------------------------------------------------------ |
| `--id ID,...`   | Card IDs to delete (comma-separated, required)         |
| `--dry-run`     | Preview cards to be deleted without actually deleting   |
| `--keep-empty-tags` | Keep empty tags after card deletion instead of pruning them |


**Dry Run:** Use `--dry-run` first. It also predicts which affected tags would become empty, without writing to Cubox. For ≤ 3 cards it includes title and URL; larger batches omit per-card details. Before a real deletion, the CLI reads the target cards and their tags; if it cannot match a tag safely, it stops before deleting cards. After deletion it checks both active and archived cards and child tags, then verifies any tag deletion. Card and tag deletion are not transactional: if cleanup fails, the cards may already be gone and the command reports this explicitly.

```bash
# Preview
cubox-cli delete --id 7435692934957108160,7435691601617225646 --dry-run

# Execute after confirming
cubox-cli delete --id 7435692934957108160,7435691601617225646
```

### `cubox-cli annotation list`

List and search annotations across all cards.

```bash
cubox-cli annotation list [flags]
```


| Flag                | Description                                                  |
| ------------------- | ------------------------------------------------------------ |
| `--color COLOR,...` | Filter by color: `Yellow`, `Green`, `Blue`, `Pink`, `Purple` |
| `--keyword TEXT`    | Search annotations                                          |
| `--start-time TIME` | Filter by start time                                         |
| `--end-time TIME`   | Filter by end time                                           |
| `--limit N`         | Page size (default 50)                                       |
| `--last-id ID`      | Cursor pagination                                            |
| `--all`             | Auto-paginate to fetch all results                           |


## Examples

### Search for articles (keyword)

```bash
cubox-cli card list --keyword "machine learning" --page 1 -o pretty
```

### Look up a card by exact URL

```bash
cubox-cli card list --url "https://example.com/article" -o pretty
```

### Semantic search (RAG)

```bash
cubox-cli card rag --query "articles about building REST APIs with authentication" -o pretty
```

### Browse cards in a specific folder

```bash
cubox-cli folder list -o text
cubox-cli card list --folder 7230156249357091393 --limit 10
```

### Read a saved article with AI insight

```bash
cubox-cli card detail --id 7247925101516031380 -o pretty
```

### Save a page and star it

```bash
cubox-cli save https://example.com --title "Example Site"
cubox-cli update --id CARD_ID --star --read
```

### Archive cards and list / restore them later

```bash
# Archive a batch of cards
cubox-cli archive --id 7444025677600260245,7443973659296793971

# Browse archived cards
cubox-cli card list --archived --limit 10

# Restore (move back) into a non-archived folder
cubox-cli unarchive --id 7444025677600260245,7443973659296793971 --folder "Reading List"
```

### Tidy up tags (rename, delete, merge)

```bash
# Rename a tag (leaf only — children follow automatically)
cubox-cli tag update --id 7295070793040398540 --new-name link

# Batch delete tags (cards keep their other tags)
cubox-cli tag delete --id 7444025677600260245,7443973659296793971

# Merge two tags into a target tag (cards re-tagged, sources deleted)
cubox-cli tag merge --source 7342187912403881105,7342187917722258501 --target 7247925099053977508
```

### Delete cards (with dry-run)

```bash
cubox-cli delete --id 7435692934957108160 --dry-run -o pretty
cubox-cli delete --id 7435692934957108160
```

### Export all annotations

```bash
cubox-cli annotation list --all -o pretty
```

### Cursor-based pagination (browsing)

```bash
cubox-cli card list --limit 5
# Use last card's ID for the next page
cubox-cli card list --limit 5 --last-id 7433152100604841820
```

### Search pagination

```bash
cubox-cli card list --keyword "AI" --page 1
cubox-cli card list --keyword "AI" --page 2
```

## Development

### Build from source

```bash
cd /path/to/exported-cubox-cli
make build        # build for current platform
make build-all    # cross-compile for all platforms
make release      # create release archives
```

### Project structure

```
cubox-cli/
  main.go                 # entry point
  cmd/                    # cobra commands
    root.go               # root command, --output flag
    auth.go               # auth login/status/logout
    folder.go             # folder list
    tag.go                # tag list/update/delete/merge
    card.go               # card list/detail/rag
    card_batch.go         # read-only batch detail command and ordered JSON
    save.go               # save web pages
    update.go             # update card
    archive.go            # batch archive / unarchive cards
    delete.go             # delete cards (with dry-run)
    annotation.go         # annotation list
    version.go            # version
  internal/
    client/               # HTTP client + API types
      card_batch.go       # bounded workers, latched stop, response-ID validation
      card_content.go     # conservative content evidence classification
    config/               # config file management
    timefmt/              # flexible time parsing
    update/               # npm update check
  scripts/                # npm distribution wrapper
  skills/cubox/           # AI Agent skill
  .github/workflows/      # CI/CD
```

## License

[MIT](LICENSE)
