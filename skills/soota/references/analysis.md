# Soota 摘要与渲染

Read the saved `transcript.md` in chunks only when the user requests a summary. Use existing segment IDs as evidence, and write an Analysis JSON file matching `schemas/analysis.v1.json`:

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
