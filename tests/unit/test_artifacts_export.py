import json

import pytest

from soota.artifacts.bundle import content_from_markdown, write_artifact, write_bundle
from soota.artifacts.export import export_bundle
from soota.errors import InputError
from soota.models import MediaItem
from soota.routing import recognize


def source(tmp_path):
    folder = tmp_path / "source"
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"))
    document = content_from_markdown(item.source, "Body\n\n![Image](media/image.png)")
    bundle = write_bundle(folder, item, content=document)
    write_artifact(folder, bundle, path="media/image.png", kind="image", format="png", content=b"synthetic image")
    return folder, item


def test_explicit_export_preserves_links_and_is_repeatable(tmp_path):
    folder, _ = source(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    exported = export_bundle(folder, vault=vault, subdir="Collected")
    assert "![Image](media/image.png)" in (exported / "body.md").read_text()
    assert (exported / "media/image.png").read_bytes() == b"synthetic image"
    record = json.loads((exported / ".soota-export.json").read_text())
    assert "media/image.png" in record["managed_sha256"]
    assert export_bundle(folder, vault=vault, subdir="Collected") == exported


def test_export_update_rejects_user_edit_before_touching_any_file(tmp_path):
    folder, item = source(tmp_path)
    exported = export_bundle(folder, destination=tmp_path / "export")
    (exported / "body.md").write_text("Handwritten material")
    before = (exported / "context.md").read_bytes()
    write_bundle(folder, item, content=content_from_markdown(item.source, "New content"))
    with pytest.raises(InputError, match="人工修改") as exc:
        export_bundle(folder, destination=tmp_path / "export")
    assert exc.value.details["conflicts"] == ["body.md"]
    assert (exported / "body.md").read_text() == "Handwritten material"
    assert (exported / "context.md").read_bytes() == before


def test_export_rejects_edited_source_and_vault_escape(tmp_path):
    folder, _ = source(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(InputError):
        export_bundle(folder, vault=vault, subdir="../escape")
    (folder / "media/image.png").write_bytes(b"changed")
    with pytest.raises(InputError, match="校验失败"):
        export_bundle(folder, destination=tmp_path / "export")
    assert not (tmp_path / "export").exists()
