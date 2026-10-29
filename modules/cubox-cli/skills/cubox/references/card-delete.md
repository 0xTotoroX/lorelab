# card delete — Dry Run Policy

Delete one or more cards by ID.

```bash
cubox-cli delete --id CARD_ID [--id ID2,...] [--dry-run]
```

## Flags


| Flag          | Description                                                    |
| ------------- | -------------------------------------------------------------- |
| `--id ID,...` | Card IDs to delete (comma-separated, required)                 |
| `--dry-run`   | Preview which cards would be deleted without actually deleting |
| `--keep-empty-tags` | Skip empty-tag inspection and cleanup |


## Output

Returns: `{ "dry_run": bool, "count": N, "cards": [...], "message": "..." }`

- JSON (`-o json` or `-o pretty`) dry-run always returns every requested ID in `cards`, in input order, with `count` matching the list length.
- When ≤ 3 cards: previews also fetch `title` and `url` when available.
- When > 3 cards: JSON entries contain only `id`; no per-card detail requests are made. Text mode keeps the count-only card display.
- With `--keep-empty-tags`, large-batch dry-run makes no HTTP requests; without it, the existing read-only tag prediction still runs.

## Dry Run Policy for AI Agents

Deleted items stay in the user's "Recently Deleted" folder for 30 days before permanent removal, but agents must still treat deletion as destructive.

1. **Always** run with `--dry-run` first before any real deletion.
2. Inspect the dry-run result against the current authorization. Present the proposed scope and ask for explicit authorization only when it is not already covered.
  - ≤ 3 cards: show the card titles returned by dry-run.
  - > 3 cards: tell the user the count (e.g. "Will delete 25 cards").
3. Only within explicit authorization for that scope, run again without `--dry-run` to perform the actual deletion. LoreLab knowledge batches must use their cleanup command so source-completeness, GitHub protection and destination-verification checks remain enforced.
4. Never skip the dry-run step.

## Example workflow

```bash
# Step 1: preview
cubox-cli delete --id CARD_A,CARD_B --dry-run
# Step 2: show user the preview, ask "Delete these 2 cards?"
# Step 3: if confirmed, execute
cubox-cli delete --id CARD_A,CARD_B
```

