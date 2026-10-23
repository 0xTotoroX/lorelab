# Soota 文章、分析与渲染

Collection ends at `context.md`. Do not polish, rewrite, summarize or generate an article unless the user requested that output. Context is Agent input, not a reading document: it may retain fragments, repeated wording and awkward sentences.

For a requested analysis or summary, read context in chunks and apply the selected prompt directly; do not create a full-article intermediate. Only an explicit detailed-article/reading request enables article composition. Then preserve the source's substance and reasoning, follow applicable local formatting rules, and do not substitute a short summary for the requested article. A saved prompt or older folder workflow does not itself authorize an extra article stage.

For supplied text that the user wants saved as concise, classified knowledge, use [knowledge workflow](knowledge.md). It preserves the paste, checks source evidence and relevant existing notes, and separates source-task completion from actual knowledge placement.

Use `transcript.md` for timestamps and evidence IDs. For legacy bundles without context, read the transcript directly. Do not use an old reading article as the source transcript, invent facts/timestamps, or silently regenerate preserved stale articles.

Use the output format and location specified by the user or local rules. A custom prompt may require sections that the built-in renderer cannot represent; do not drop or flatten them merely to fit its schema. Keep source transcripts and provenance available for verification, and do not overwrite user edits without authorization.

For a standard Soota summary that fits the renderer, use existing segment IDs as evidence and write an Analysis JSON file matching `schemas/analysis.v1.json`:

```json
{
  "schema_version": 1,
  "summary": "...",
  "key_points": [{"text": "...", "evidence": ["seg-000001"]}],
  "chapters": [{"title": "...", "start_ms": 0, "end_ms": 12000, "summary": "..."}],
  "tags": ["..."],
  "language": "zh"
}
```

Run `soota render --bundle PATH/manifest.json --analysis PATH/analysis.json --json` only for the requested analysis output. It writes `content.md` and analysis metadata without modifying source context or transcripts. Existing `content.md` requires an authorized `--force` replacement; invalid Analysis never overwrites it. Report the content path, and do not paste a long transcript into the final reply.
