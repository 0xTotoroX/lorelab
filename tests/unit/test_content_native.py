from __future__ import annotations

from pathlib import Path

import pytest

from soota.content import native
from soota.content.native_bindings import content_candidates, media_binding, normalize_rows
from soota.content.native_types import NativeOperation
from soota.errors import ContractError, InputError, SourceError


def command(operation, names=(), access="read"):
    site, name = operation.split("/")
    return {
        "command": operation,
        "site": site,
        "name": name,
        "access": access,
        "browser": True,
        "args": [{"name": name, "type": "str"} for name in names],
    }


@pytest.fixture
def install(monkeypatch):
    def setup(commands, execute):
        monkeypatch.setattr(native.opencli_commands, "commands", lambda settings: commands)
        monkeypatch.setattr(native.opencli_commands, "execute", execute)

    return setup


def test_saved_article_isolated_and_preserves_body(settings, tmp_path, install):
    calls = []

    def execute(settings, cmd, params, *, allow_write):
        assert allow_write is False
        assert params["download-images"] is False
        directory = Path(params["output"])
        calls.append(directory)
        path = directory / "same-title.md"
        path.write_text("# 标题\n\n原文  原文\n重复\n重复\n")
        return [{"title": "同标题", "status": "success", "saved": str(path)}]

    install([command("web/read", ["url", "output", "download-images"])], execute)
    a = native.capture_content(settings, "https://example.test/a", tmp_path)
    b = native.capture_content(settings, "https://example.test/b", tmp_path)
    assert a.body == "# 标题\n\n原文  原文\n重复\n重复\n"
    assert a.raw[0]["saved"] != b.raw[0]["saved"]
    assert calls[0] != calls[1]
    assert a.source_url == "https://example.test/a"


@pytest.mark.parametrize("status", ["failed", "failed — no content", None])
def test_success_exit_with_failed_article_is_rejected(settings, tmp_path, install, status):
    install(
        [command("web/read", ["url", "output"])],
        lambda *args, **kwargs: [{"title": "failed", "status": status, "saved": "-"}],
    )
    with pytest.raises(SourceError):
        native.capture_content(settings, "https://example.test/a", tmp_path)


@pytest.mark.parametrize("kind", ["outside", "empty", "missing", "symlink"])
def test_untrusted_saved_path_is_rejected(settings, tmp_path, install, kind):
    outside = tmp_path / "private.md"
    outside.write_text("must not read")

    def execute(settings, cmd, params, *, allow_write):
        path = Path(params["output"]) / "article.md"
        if kind == "outside":
            path = outside
        elif kind == "empty":
            path.touch()
        elif kind == "symlink":
            path.symlink_to(outside)
        return [{"title": "a", "status": "success", "saved": str(path)}]

    install([command("web/read", ["url", "output"])], execute)
    with pytest.raises(ContractError):
        native.capture_content(settings, "https://example.test/a", tmp_path / "run")


def test_inline_article_and_field_value_note(settings, tmp_path, install):
    install(
        [command("twitter/article", ["tweet-id"])],
        lambda *a, **kw: [{"title": "Title", "content": "**original**\n\nbody", "url": "unused"}],
    )
    content = native.capture_content(settings, "https://x.com/example/status/123", tmp_path)
    assert content.body == "**original**\n\nbody"
    assert content.operation == "twitter/article"

    def execute(settings, cmd, params, *, allow_write):
        assert params["note-id"].endswith("?xsec_token=fixture-token")
        return [{"field": "title", "value": ""}, {"field": "content", "value": "原文\n原文"}]

    install([command("xiaohongshu/note", ["note-id"])], execute)
    note = native.capture_content(
        settings, "https://www.xiaohongshu.com/explore/123?xsec_token=fixture-token", tmp_path
    )
    assert note.body == "原文\n原文" and note.format == "text"


def test_convert_contract_can_be_reused_by_future_command(tmp_path):
    result = NativeOperation(
        raw=[{"title": "T", "content": "B"}], provider="opencli", operation="future/article", workdir=tmp_path
    )
    assert native.convert_content(result, "https://example.test/a", result_schema="inline-markdown").body == "B"


def test_no_automatic_fallback_after_dispatch(settings, tmp_path, install):
    calls = []

    def execute(settings, cmd, params, *, allow_write):
        calls.append(cmd["command"])
        raise SourceError("upstream failed")

    install([command("zhihu/download", ["url", "output"]), command("web/read", ["url", "output"])], execute)
    with pytest.raises(SourceError):
        native.capture_content(settings, "https://zhuanlan.zhihu.com/p/123", tmp_path)
    assert calls == ["zhihu/download"]


def test_capture_operation_rejects_writes_and_stdout(settings, tmp_path, install):
    def fail(*a, **kw):
        raise AssertionError("must not dispatch")

    install([command("twitter/post", ["text"], access="write"), command("web/read", ["url", "stdout"])], fail)
    with pytest.raises(InputError):
        native.capture_operation(settings, "opencli.twitter.post", {"text": "no"}, tmp_path)
    with pytest.raises(InputError):
        native.capture_operation(
            settings, "opencli.web.read", {"url": "https://example.test", "stdout": True}, tmp_path
        )


def test_native_unknown_data_stays_native(settings, tmp_path, install):
    raw = {"unfamiliar": [{"url": "https://example.test", "content": "do not infer"}]}
    install([command("future/read", ["id"])], lambda *a, **kw: raw)
    result = native.capture_operation(settings, "opencli.future.read", {"id": "abc"}, tmp_path)
    assert result.raw is raw and result.entries is None


def test_url_rows_only_normalize_explicit_contracts():
    rows = [{"title": "T", "url": "https://example.test/video", "id": "123"}]
    assert normalize_rows("youtube/search", rows)[0].id == "123"
    assert normalize_rows("future/search", rows) is None
    assert normalize_rows("youtube/channel", [{"field": "title", "value": "00:00 | https://example.test"}]) is None
    assert normalize_rows("youtube/search", [{"title": "bad", "url": "file:///etc/passwd"}]) is None
    assert normalize_rows("youtube/search", rows + [{"title": "missing url"}]) is None


def test_media_files_require_actual_nonempty_outputs(settings, tmp_path, install):
    def execute(settings, cmd, params, *, allow_write):
        directory = Path(params["output"])
        (directory / "1.jpg").write_bytes(b"fixture-image")
        (directory / "2.jpg").touch()
        (directory / "3.part").write_bytes(b"partial")
        return [{"status": "success", "type": "image"}, {"status": "failed", "type": "image"}]

    install([command("xiaohongshu/download", ["note-id", "output"])], execute)
    result = native.capture_media(settings, "https://xhslink.com/fixture", tmp_path)
    assert [p.name for p in result.files] == ["1.jpg"]
    assert result.verified is False
    assert len(result.warnings) == 2


def test_media_reported_success_without_file_fails(settings, tmp_path, install):
    install([command("twitter/download", ["tweet-url", "output"])], lambda *a, **kw: [{"status": "success"}])
    with pytest.raises(ContractError):
        native.capture_media(settings, "https://x.com/example/status/123", tmp_path)


def test_url_bindings_preserve_relevant_query_and_reject_wrong_host():
    op, params = media_binding("https://www.bilibili.com/video/BV12345678?p=2")
    assert op == "bilibili/download" and params["page"] == "2"
    assert content_candidates("https://zhihu.com.evil.test/p/123")[0][0] == "web/read"
    with pytest.raises(InputError):
        media_binding("https://www.bilibili.com/video/BV12345678?p=0")
    with pytest.raises(InputError):
        content_candidates("https://user:secret@example.test/")


def test_media_files_keep_numeric_carousel_order(settings, tmp_path, install):
    def execute(settings, cmd, params, *, allow_write):
        for index in (10, 2, 1):
            (Path(params["output"]) / f"note_{index}.jpg").write_bytes(b"fixture-image")
        return [{"status": "success", "type": "image"} for _ in range(3)]

    install([command("xiaohongshu/download", ["note-id", "output"])], execute)
    result = native.capture_media(settings, "https://xhslink.com/fixture", tmp_path)
    assert [p.name for p in result.files] == ["note_1.jpg", "note_2.jpg", "note_10.jpg"]
