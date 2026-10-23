# Fork 说明 / About this fork

This is a fork of [OLCUBO/cubox-cli](https://github.com/OLCUBO/cubox-cli) that **unlocks the full web/app API group** on top of the official CLI: folder write operations, batch card operations, recycle bin, marks (highlights) management, reading lists, import/export tasks, account info and AI features.

这是官方 cubox-cli 的 fork：在官方能力之外，解锁了 **web/app 组的全部接口**——收藏夹写操作、批量卡片操作、回收站、标注管理、阅读清单、导入/导出任务、账号信息与 AI 功能。

```
# Folder management (web/app group)
cubox-cli folder delete --id ID[,ID2,...] [--dry-run] [--hard]
cubox-cli folder new --name NAME [--parent PARENT_ID]
cubox-cli folder rename --id ID --new-name NAME
cubox-cli folder archive --id ID[,ID2] --on|--off
cubox-cli folder move --id ID --parent PARENT_ID [--index N]   # N: 0-based, default last

# Batch card operations (web/app group)
cubox-cli card star --id ID[,ID2] --on|--off
cubox-cli card read --id ID[,ID2,...]            # batch mark as read
cubox-cli card move --id ID[,ID2] --folder-id FID  # batch move to folder
cubox-cli card tag --id ID[,ID2] --add name,name [--delete-tag-ids ID]

# Batch card detail reads (CLI group, read-only)
cubox-cli card batch --id CARD1,CARD2 [--ids-file card-ids.txt] --workers 2

# Recycle bin
cubox-cli recycle list [--page N]
cubox-cli recycle recover --id ID[,ID2,...]
cubox-cli recycle clean --id ID[,ID2,...]        # permanent, destructive

# Tags (CLI and web/app groups)
cubox-cli tag new --name NAME [--parent TAG_ID]
cubox-cli tag move --id TAG_ID --parent PARENT_TAG_ID  # preserves tag ID and card links
cubox-cli tag topic --id CARD_ID [--apply]              # AI topic preview; add approved tags only
cubox-cli tag topic collect --id CARD1,CARD2 --out PLAN # collect new concepts locally
cubox-cli tag topic review --plan PLAN --name NAME --decision approved|merged|rejected
cubox-cli tag topic auto-review --plan PLAN          # merge synonyms and auto-approve repeated, supported topics locally
cubox-cli tag topic backfill --plan PLAN [--apply]       # reclassify reviewed batch
cubox-cli tag topic backfill --plan PLAN --auto [--apply] # keep pending terms; apply creates approved tags before backfill
cubox-cli tag prune-empty --name PICSED [--apply] # preview or remove an already-empty leaf tag
cubox-cli delete --id CARD_ID [--dry-run] [--keep-empty-tags] # prunes affected empty leaf tags by default
cubox-cli tag sort --json '{...}'                # experimental drag-order payload

# Marks (highlights)
cubox-cli mark list [--page N] [--keyword K]
cubox-cli mark count
cubox-cli mark delete --id ID[,ID2,...]
cubox-cli mark color --id ID[,ID2] --color 1..5  # 1=Yellow 2=Green 3=Blue 4=Pink 5=Purple
cubox-cli mark export [--card ID] [--mark ID]
cubox-cli mark export-text [--card ID] [--mark ID]

# Reading lists
cubox-cli lists list
cubox-cli lists new --title TITLE [--intro INTRO]
cubox-cli lists delete --list ID
cubox-cli lists update --list ID [--title T] [--intro I]
cubox-cli lists publish --list ID --on|--off
cubox-cli lists cards --list ID [--page N] [--size M]
cubox-cli lists add-item --list ID --card ID [--highlight] [--note]
cubox-cli lists remove-item --list ID --card ID
cubox-cli lists collect --list ID --card ID
cubox-cli lists collect-all --list ID
cubox-cli lists sort --list ID --card ID1,ID2    # full ordered list
cubox-cli lists check --card ID[,ID2]            # which lists contain these cards

# Export
cubox-cli export status        # today's export count + import readiness
cubox-cli export bookmarks     # request full-library export (v3 endpoint)
cubox-cli export mail --email ADDR --card ID[,ID2,...]   # async export via email (verified)

# Import (official task pipeline)
cubox-cli import bookmarks --file bookmarks.html   # upload (HTML; folder tree preserved)
cubox-cli import progress      # poll the import task

# Account
cubox-cli account apikey       # API extension key(s)
cubox-cli account settings     # reading settings
cubox-cli account settings-update --json '{...}'   # experimental: full settings object
cubox-cli account sync         # Notion / Flowus / Readwise sync status
cubox-cli account insight --card CARD_ID   # a card's AI insight
cubox-cli account insight-state --card CARD_ID
cubox-cli account more-qas --card CARD_ID  # follow-up Q&As of the insight
cubox-cli account mail         # Mail Drop (email-in) settings

# AI
cubox-cli ai generate --card CARD_ID   # stream AI insight generation (SSE; consumes AI quota)
cubox-cli ai ask --question Q [--context TEXT]   # ⚠ experimental: endpoint verified
                                       # (POST, form-urlencoded, OpenAI-delta SSE)
                                       # but the required field set is not fully
                                       # mapped yet — needs one live request capture
```

- `folder delete` defaults to **safe mode**: remaining cards are first moved to
  Uncategorized, then the folder is deleted (mirroring the Cubox app's own
  behavior — cards are never lost). `--hard` skips the move step.
- `--dry-run` previews the operation without touching anything.

### Safety mechanisms / 安全机制

Born from the 2026-10-09 incident (an unthrottled debug loop deleted the
system "Uncategorized" group and corrupted the server-side account group
tree, requiring official repair):

1. **System-group guard**: `folder delete / rename / move / archive` refuse
   to operate on the account's system "Uncategorized" group (the one with an
   empty name / the collectionBox) — deleting it corrupts the server group
   tree. Applies to `--dry-run` too.
2. **Shared Client request throttle**: requests using the same Client are
   admitted at least 500 ms apart. All `card batch` workers share that Client.
3. **Batch circuit breaker**: `card batch` latches a stop after three consecutive
   completed errors, including transport, HTTP, API, payload, and ID-validation
   failures. Already admitted requests finish; a late success cannot reopen the
   batch. Other commands retain their existing error behavior.
4. `folder delete` keeps its **safe mode** (cards moved to Uncategorized
   before the folder is deleted) and `--dry-run` preview.

### Batch card detail reads / 批量详情读取

`card batch` reads one detail per deduplicated ID with bounded concurrency
(`--workers 2` by default, allowed 1..4). Combine comma-separated `--id` entries
with `--ids-file` (one ID per line); flag IDs precede file IDs. Output order is
fixed even when responses finish out of order. A stopped batch retains successes,
errors, and the reason each remaining request was skipped.

Stdout always has `schema_version: 1`, `kind: "cubox_card_batch"`, `items`, and
`counts`. Partial failure writes the result and exits 1. Update notices stay on
stderr, and `-o text` still emits JSON. The command validates returned card IDs
and exposes only fixed error messages plus numeric HTTP/API codes. It performs
no writes, retries, redirects, or original-site fetches. `card detail` keeps its
existing semantics.

`content_status` is `body_available`, `description_only`, `link_only`, or `empty`
on success, and null on errors/skips. Empty/null, pure links, and recognized login
placeholders do not count as body text. `body_available` never means the original
post is complete; navigation and interface instructions may still count as text.
See the [complete batch contract and workflow](skills/cubox/references/card-batch.md).

The implementation separates `cmd/card_batch.go` (flags, local ID files, JSON)
from `internal/client/card_batch.go` (workers, stop, validation) and
`internal/client/card_content.go` (conservative Markdown classification). They
reuse the existing Client transport/throttle and CardDetail type. Goldmark parses
Markdown locally; neither classification nor tests require an account.

### Save hardening / 保存加固

- `save --json` now **batches to ≤20 entries per request** (the server
  silently truncates larger batches while reporting success) and **stops on
  the first failed batch** with a count of what was saved before it.
- `save --verify`: after saving, audit every URL to confirm it actually
  landed (slower; parsing is async so freshly saved cards may need minutes
  before they resolve).
- `save --folder "a/b"` resolves the nested path level by level (creating
  missing folders) instead of creating a flat folder whose name contains a
  slash.
- Note: nested folder creation requires **Cubox Pro** (free accounts get
  -1025 on the second level).
- `folder move --id X` (no --parent) moves a folder to the root level via
  move/another with a JSON-null parentGroupId. WARNING: `group/update` with
  an EMPTY parentGroupId DELETES the group — never send that.

### Request-encoding notes (reverse-engineered)

The web/app group uses **several different body encodings**, and the server
rejects the wrong one with `-5000 Invalid input` / `must not be blank`:

| Endpoints | Encoding |
|---|---|
| `group/new`, `group/update`, `group/move/another`, `norm/cards/export/async`, `settings/read/update`, `marks/*`, `recycle/*` | **form-urlencoded** |
| `group/delete/{id}`, `group/moveSearchEnginesOut/{id}` | no body (path param) |
| `reading-list*`, `lists/items/*`, `v2/bookmark/import` | multipart/form-data |
| `ai/ask`, `card/insight/generate/stream` | form-urlencoded request, **SSE** response (OpenAI delta format) |

(The web app's own HTTP client serializes every POST body with a
query-string encoder — including bodies that look like JSON in its source,
e.g. the recycle endpoints' `searchEngines` field is a JSON-*stringified*
array inside a form body.)

`folder move` may take a while server-side (tree reorder); the client uses a
120s timeout for form posts, and a timed-out request may still have been
applied — re-check with `folder list`.

### Not covered / 未覆盖

- `ai/ask` free-form Q&A: command shipped as **experimental** — the wire
  format is mapped but one required form field is still unidentified
  (needs one live request capture from the web/app).
- Reading-list per-item pin/update.
- Everything else in the web/app group is covered.

## How it works / 工作原理

Cubox exposes two separate API groups with **mutually isolated credentials**:

| API group | Endpoints | Auth style | Token |
|---|---|---|---|
| CLI group | `/c/api/cli/*` | `Authorization: Bearer <token>` | API Extension token (`auth login`) |
| Web/App group | `/c/api/*` | `Authorization: <token>` (**bare**, no Bearer prefix) | Cubox.app login token |

All pre-existing commands keep using the CLI group (unchanged). The new folder
write commands use the Web/App group — the same endpoints the Cubox web app and
the native Cubox.app call:

- `POST /c/api/group/moveSearchEnginesOut/{id}` — move cards to Uncategorized + delete folder
- `POST /c/api/group/delete/{id}` — direct delete
- `POST /c/api/group/new` — create (expects `application/x-www-form-urlencoded`)
- `POST /c/api/group/update` — rename (expects `application/x-www-form-urlencoded`)
- `GET /c/api/v2/group/my` — list folders (camelCase payload)

Note the request format details discovered while implementing: `group/new` and
`group/update` reject JSON bodies with `-5000 Invalid input` — they require
form-urlencoded encoding.

## App token resolution / App token 来源

The web/app group token (`Ctoken`) is resolved in this order:

1. `CUBOX_CTOKEN` environment variable
2. macOS: read automatically from the logged-in Cubox.app
   (`~/Library/Group Containers/group.com.guaiqi.cubox/...plist`)

## Caveats / 注意事项

- These endpoints are **undocumented**; Cubox may change them at any time.
- The app token is tied to the Cubox.app login session (logging out
  invalidates it).
- Use responsibly: your own account, moderate request rates.

## License

MIT (inherited from the upstream project).
