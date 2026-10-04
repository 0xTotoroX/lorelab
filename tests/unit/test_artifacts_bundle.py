import json

import pytest

from soota.artifacts.bundle import (
    content_from_markdown,
    load_bundle,
    safe_path,
    verify_artifacts,
    write_artifact,
    write_bundle,
)
from soota.artifacts.models import ContentBlock, ContentDocument
from soota.errors import InputError, SourcePreserved
from soota.models import (
    ContentBundleManifest,
    MediaItem,
    TranscriptDocument,
    TranscriptManifest,
    TranscriptSegment,
    TranscriptSource,
    TranscriptStatus,
)
from soota.render.bundle import write_bundle as write_legacy
from soota.routing import recognize


@pytest.fixture
def item():
    return MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"), title="Example")


@pytest.fixture
def document():
    return TranscriptDocument(
        status=TranscriptStatus.READY,
        source=TranscriptSource.OFFICIAL,
        segments=[
            TranscriptSegment(
                segment_id="seg-000001",
                start_ms=0,
                end_ms=1500,
                text="原文\n重复\n重复",
                source=TranscriptSource.OFFICIAL,
            ),
        ],
    )


def test_metadata_only_and_independent_media(tmp_path, item):
    bundle = write_bundle(tmp_path, item)
    assert set(bundle.files) == {"manifest.json"}
    assert not (tmp_path / "transcript.md").exists() and not (tmp_path / "context.md").exists()
    original = tmp_path.parent / "original.mp4"
    original.write_bytes(b"synthetic media bytes")
    artifact = write_artifact(
        tmp_path,
        bundle,
        path="media/video.mp4",
        kind="video",
        format="mp4",
        content=original,
        verification="media",
        attributes={"duration": 5.5},
    )
    assert artifact.attributes["duration"] == 5.5 and artifact.bytes == original.stat().st_size
    assert original.read_bytes() == (tmp_path / "media/video.mp4").read_bytes()
    assert verify_artifacts(tmp_path, load_bundle(tmp_path)) == []
    (tmp_path / "media/video.mp4").write_bytes(b"changed")
    assert verify_artifacts(tmp_path, bundle) == ["changed:media/video.mp4"]


def test_content_preserves_body_order_whitespace_and_stable_ids(tmp_path, item):
    text = "# Heading\n\nFirst\nline\n\n\n![Image](media/image.png)\n\nFirst\nline\n"
    content = content_from_markdown(item.source, text, "Article", "full")
    assert content.body_md == text
    assert len({block.block_id for block in content.blocks}) == len(content.blocks)
    again = content_from_markdown(item.source, text, "Article", "full")
    assert [b.block_id for b in content.blocks] == [b.block_id for b in again.blocks]
    bundle = write_bundle(tmp_path, item, content=content)
    assert (tmp_path / "body.md").read_text() == text
    assert bundle.content.scope == "full" and bundle.transcript.status == "not_requested"
    assert "![Image](media/image.png)" in (tmp_path / "context.md").read_text()
    assert not (tmp_path / "transcript.md").exists()


def test_v1_load_read_only_and_update_keeps_article(tmp_path, item, document):
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status=document.status))
    folder = write_legacy(tmp_path, item, document, manifest, None)
    (folder / "content.md").write_text("User article")
    before = (folder / "manifest.json").read_bytes()
    bundle = load_bundle(folder)
    assert bundle.schema_version == 2 and bundle.context_fingerprint
    assert (folder / "manifest.json").read_bytes() == before
    bundle = write_bundle(folder, item, document=document, force=True)
    assert (folder / "content.md").read_text() == "User article"
    assert json.loads((folder / "manifest.json").read_text())["schema_version"] == 2


def test_empty_attempt_and_different_source_preserve_files(tmp_path, item, document):
    write_bundle(tmp_path, item, document=document)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    with pytest.raises(SourcePreserved):
        write_bundle(tmp_path, item, document=TranscriptDocument(status=TranscriptStatus.MISSING))
    other = item.model_copy(update={"source": recognize("https://www.youtube.com/watch?v=Example0002")})
    with pytest.raises(InputError, match="不同来源"):
        write_bundle(tmp_path, other, document=document)
    assert all((tmp_path / name).read_bytes() == value for name, value in before.items())


def test_manual_source_edit_detected_before_any_write(tmp_path, item, document):
    write_bundle(tmp_path, item, document=document)
    (tmp_path / "context.md").write_text("User change")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    with pytest.raises(InputError, match="未覆盖"):
        write_bundle(tmp_path, item, document=document)
    assert all((tmp_path / name).read_bytes() == value for name, value in before.items())


@pytest.mark.parametrize("name", ["../outside", "/absolute", "a/../../outside", "a\\outside", "a//b", "./x"])
def test_relative_paths_reject_escape(tmp_path, name):
    with pytest.raises(InputError):
        safe_path(tmp_path, name)


def test_symlink_escape_rejected(tmp_path, item):
    bundle = write_bundle(tmp_path, item)
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(InputError, match="符号链接"):
        write_artifact(tmp_path, bundle, path="escape/data.json", kind="data", format="json", content="{}")


def test_reserved_paths_and_manifest_symlink_rejected(tmp_path, item):
    bundle = write_bundle(tmp_path, item)
    for name in ("manifest.json", ".soota-export.json"):
        with pytest.raises(InputError):
            write_artifact(tmp_path, bundle, path=name, kind="data", format="json", content="{}")
    (tmp_path / "manifest.json").unlink()
    outside = tmp_path.parent / "external-manifest.json"
    outside.write_text(bundle.model_dump_json())
    (tmp_path / "manifest.json").symlink_to(outside)
    with pytest.raises(InputError, match="符号链接"):
        load_bundle(tmp_path)


def test_combined_body_and_transcript_context(tmp_path, item, document):
    content = ContentDocument(source=item.source, blocks=[ContentBlock(text="Article body")])
    bundle = write_bundle(tmp_path, item, document=document, content=content)
    context = (tmp_path / "context.md").read_text()
    assert "Article body" in context and "原文\n重复\n重复" in context
    assert bundle.content and bundle.transcript.status == "ready"


def test_incremental_sources_keep_both_context_parts(tmp_path, item, document):
    content = content_from_markdown(item.source, "Body")
    write_bundle(tmp_path, item, document=document)
    before = (tmp_path / "transcript.md").read_bytes()
    write_bundle(tmp_path, item, content=content)
    assert (tmp_path / "transcript.md").read_bytes() == before
    assert "Body" in (tmp_path / "context.md").read_text()
    assert "原文" in (tmp_path / "context.md").read_text()
    write_bundle(tmp_path, item, document=document)
    assert "Body" in (tmp_path / "context.md").read_text()
    assert "原文" in (tmp_path / "context.md").read_text()
    with pytest.raises(SourcePreserved):
        write_bundle(tmp_path, item, document=TranscriptDocument(status=TranscriptStatus.MISSING), content=content)
