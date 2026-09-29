from __future__ import annotations

import json
from pathlib import Path

from soota.models import Analysis, AnalysisStatus, ContentBundleManifest, MediaItem, TranscriptDocument
from soota.render.markdown import render_content, render_transcript
from soota.storage.atomic import atomic_write


def bundle_dir(output_root: Path, item: MediaItem) -> Path:
    return output_root / item.source.platform / item.source.id


def write_bundle(
    output_root: Path,
    item: MediaItem,
    document: TranscriptDocument,
    manifest: ContentBundleManifest,
    analysis: Analysis | None,
    *,
    force: bool = False,
) -> Path:
    folder = bundle_dir(output_root, item)
    return write_bundle_to(folder, item, document, manifest, analysis, force=force)


def write_bundle_to(
    folder: Path,
    item: MediaItem,
    document: TranscriptDocument,
    manifest: ContentBundleManifest,
    analysis: Analysis | None,
    *,
    force: bool = False,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    content_path = folder / "content.md"
    transcript_path = folder / "transcript.md"
    manifest_path = folder / "manifest.json"

    if analysis is not None:
        content = render_content(item, document, manifest, analysis)
        atomic_write(content_path, content)
        manifest.analysis = manifest.analysis.model_copy(update={"status": AnalysisStatus.READY, "path": "content.md"})
    elif force or not content_path.is_file():
        atomic_write(content_path, render_content(item, document, manifest, None))
        if manifest.analysis.status != AnalysisStatus.READY:
            manifest.analysis = manifest.analysis.model_copy(update={"path": "content.md"})
    elif not force and content_path.is_file() and analysis is None:
        pass

    atomic_write(transcript_path, render_transcript(item, document))
    manifest.transcript.path = "transcript.md"
    manifest.transcript.segments = len(document.segments)
    manifest.transcript.status = document.status
    manifest.transcript.source = document.source
    manifest.transcript.language = document.language
    manifest.files.update(
        {
            "content.md": "content.md",
            "transcript.md": "transcript.md",
            "manifest.json": "manifest.json",
        }
    )
    atomic_write(
        manifest_path,
        json.dumps(json.loads(manifest.model_dump_json()), ensure_ascii=False, indent=2) + "\n",
    )
    return folder
