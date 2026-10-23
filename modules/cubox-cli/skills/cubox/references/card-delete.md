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


## Output

Returns: `{ "dry_run": bool, "count": N, "cards": [...], "message": "..." }`

- When ≤ 3 cards: `cards` array includes `id`, `title`, `url` fetched from server.
- When > 3 cards: `cards` is omitted; only `count` is shown (avoids heavy per-card API calls).

## Dry Run Policy for AI Agents

Deleted items stay in the user's "Recently Deleted" folder for 30 days before permanent removal, but agents must still treat deletion as destructive.

1. **Always** run with `--dry-run` first before any real deletion.
2. Inspect the dry-run result against the current authorization. Present the proposed scope and ask for explicit authorization only when it is not already covered.
  - ≤ 3 cards: show the card titles returned by dry-run.
  - > 3 cards: tell the user the count (e.g. "Will delete 25 cards").
3. Only within explicit authorization for that scope, run again without `--dry-run` to perform the actual deletion. LoreHub batches must use their cleanup command so source-completeness, GitHub protection and destination-verification checks remain enforced.
4. Never skip the dry-run step.

## Example workflow

```bash
# Step 1: preview
cubox-cli delete --id CARD_A,CARD_B --dry-run
# Step 2: show user the preview, ask "Delete these 2 cards?"
# Step 3: if confirmed, execute
cubox-cli delete --id CARD_A,CARD_B
```

