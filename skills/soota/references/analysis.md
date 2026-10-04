# Soota 文章、分析与渲染

Read the saved `transcript.md` in chunks when the user requests an article or analysis. Follow the destination's local processing rules and selected prompt. If they specify transcript → full article → prompt processing, preserve that order: retain the source's substance and reasoning in the article, then apply the prompt to it while consulting the timestamped transcript for evidence. Do not replace the article with a summary or invent facts and timestamps to fill requested sections.

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

Run `soota render --bundle PATH/manifest.json --analysis PATH/analysis.json --json`. An invalid Analysis must not overwrite a valid `content.md`; the CLI enforces this. Report the content path, and do not paste a long transcript into the final reply.
