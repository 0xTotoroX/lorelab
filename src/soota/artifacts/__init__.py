"""Content documents, verified artifacts and backward-compatible content bundles."""

from soota.artifacts.bundle import (
    content_from_markdown,
    load_bundle,
    load_transcript,
    save_bundle,
    verify_artifacts,
    write_artifact,
    write_bundle,
)
from soota.artifacts.models import Artifact, BundleV2, ContentBlock, ContentDocument

__all__ = [
    "Artifact",
    "BundleV2",
    "ContentBlock",
    "ContentDocument",
    "content_from_markdown",
    "load_bundle",
    "load_transcript",
    "save_bundle",
    "verify_artifacts",
    "write_artifact",
    "write_bundle",
]
