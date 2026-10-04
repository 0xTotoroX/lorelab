import ast
from pathlib import Path

import pytest

from soota.errors import ContractError, InputError
from soota.models import (
    CaptionAcquisition,
    CaptionPayload,
    MediaItem,
    TranscriptDocument,
    TranscriptManifest,
    TranscriptSource,
)
from soota.render.markdown import render_context, render_transcript
from soota.routing import recognize
from soota.transcripts.acquisition import acquire_captions
from soota.transcripts.captions import parse_transcript_markdown
from soota.transcripts.conversion import convert_captions, parse_payload
from soota.transcripts.promotions import filter_promotions


def parse(fmt, body):
    return parse_payload(CaptionPayload(format=fmt, body=body), language="zh", source=TranscriptSource.OFFICIAL)


def values(segments):
    return [(s.start_ms, s.end_ms, s.text) for s in segments]


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("srt", "1\n00:00:01,234 --> 00:00:02,345\n甲\n乙"),
        ("vtt", "WEBVTT\n\ncaption-id\n00:01.234 --> 00:02.345 align:start\n甲\n乙"),
        (
            "ttml",
            '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="1.234s" end="2.345s">甲<br/>乙</p></div></body></tt>',
        ),
        ("srv1", '<transcript><text start="1.234" dur="1.111">甲\n乙</text></transcript>'),
        ("srv2", '<timedtext><text t="1234" d="1111">甲\n乙</text></timedtext>'),
        ("srv3", '<timedtext><body><p t="1234" d="1111"><s t="0">甲</s>\n<s t="200">乙</s></p></body></timedtext>'),
        ("json3", {"events": [{"tStartMs": 1234, "dDurationMs": 1111, "segs": [{"utf8": "甲\n乙"}]}]}),
        ("bilibili-json", {"body": [{"from": 1.234, "to": 2.345, "content": "甲\n乙"}]}),
        ("opencli-youtube", [{"start": "1.234s", "end": "2.345s", "text": "甲\n乙"}]),
        ("opencli-bilibili", [{"from": "1.234s", "to": "2.345s", "content": "甲\n乙"}]),
        ("opencli-mcp", [{"from_s": 1.234, "to_s": 2.345, "content": "甲\n乙"}]),
        ("whisper-json", {"segments": [{"start": 1.234, "end": 2.345, "text": "甲\n乙"}]}),
        ("whisper-jsonl", '{"start":1.234,"end":2.345,"text":"甲\\n乙"}\n'),
    ],
)
def test_formats_have_same_text_and_millisecond_timeline(fmt, body):
    result = parse(fmt, body)
    assert values(result) == [(1234, 2345, "甲\n乙")]
    assert result[0].segment_id == "seg-000001"
    assert result[0].source == TranscriptSource.OFFICIAL
    assert result[0].language == "zh"


@pytest.mark.parametrize(
    "fmt,body",
    [
        (
            "json3",
            {
                "events": [
                    {"tStartMs": 2000, "dDurationMs": 1000, "segs": [{"utf8": "重复\n 原文 "}]},
                    {"tStartMs": 0, "dDurationMs": 3000, "segs": [{"utf8": "重复\n 原文 "}]},
                ]
            },
        ),
        ("srt", "2\n00:00:02,000 --> 00:00:03,000\n重复\n 原文 \n\n1\n00:00:00,000 --> 00:00:03,000\n重复\n 原文 \n"),
        (
            "srv3",
            '<timedtext><body><w t="0"/><p t="2000" d="1000">重复\n 原文 </p>'
            '<p t="0" d="3000" a="1">重复\n 原文 </p></body></timedtext>',
        ),
    ],
)
def test_repetition_order_and_internal_newlines_are_not_rewritten(fmt, body):
    result = parse(fmt, body)
    assert [s.start_ms for s in result] == [2000, 0]
    assert [s.segment_id for s in result] == ["seg-000001", "seg-000002"]
    assert all("重复\n 原文" in s.text for s in result)


def test_vtt_markup_and_noncue_blocks():
    text = (
        "\ufeffWEBVTT\r\n\r\nNOTE ignored --> metadata\r\n\r\nSTYLE\r\n::cue { color: red; }\r\n\r\n"
        "REGION\r\nid:bottom\r\n\r\n00:00.010 --> 00:01.020 region:bottom\r\n"
        "<v Narrator><c.red>甲 &amp; 乙</c>\r\n<00:00.500><i>第二行</i> &lt;b&gt; 1 < 2</v>\r\n"
    )
    assert values(parse("vtt", text)) == [(10, 1020, "甲 & 乙\n第二行 <b> 1 < 2")]


def test_ttml_parent_time_clipping_multiple_nested_divs_and_space():
    body = """<tt xmlns="http://www.w3.org/ns/ttml"><body begin="1s" end="10s"><div begin="2s">
    <p dur="2s" xml:space="preserve"> 甲 <span>乙</span><br/> 丙 </p>
    <div begin="1s"><p begin="2s" end="20s">末句</p></div></div></body></tt>"""
    assert values(parse("ttml", body)) == [(3000, 5000, " 甲 乙\n 丙 "), (6000, 10000, "末句")]


@pytest.mark.parametrize(
    "attrs,begin,dur,expected",
    [
        ('ttp:frameRate="25"', "25f", "00:00:00:12", (1000, 1480)),
        ('ttp:frameRate="30" ttp:frameRateMultiplier="1000 1001"', "30f", "30f", (1001, 2002)),
        ('ttp:frameRate="25" ttp:subFrameRate="2"', "00:00:00:01.1", "1f", (60, 100)),
        ('ttp:tickRate="100"', "10t", "20t", (100, 300)),
        ('ttp:frameRate="25"', "25t", "25t", (1000, 2000)),
        ("", "1t", "2t", (1000, 3000)),
    ],
)
def test_ttml_frame_and_tick_clocks(attrs, begin, dur, expected):
    body = (
        f'<tt xmlns:ttp="http://www.w3.org/ns/ttml#parameter" {attrs}><body>'
        f'<p begin="{begin}" dur="{dur}">字</p></body></tt>'
    )
    assert values(parse("ttml", body)) == [(*expected, "字")]


@pytest.mark.parametrize(
    "body",
    [
        '<tt xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:timeBase="clock"><body/></tt>',
        '<tt><body timeContainer="seq"><p dur="1s">字</p></body></tt>',
        '<tt><body><p begin="0s" dur="1s"><span begin=".5s">字</span></p></body></tt>',
        '<tt><body><p begin="2s" end="1s">字</p></body></tt>',
    ],
)
def test_ttml_unsupported_or_invalid_timing_fails_explicitly(body):
    with pytest.raises(ContractError):
        parse("ttml", body)


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("xml", '<i><d p="1,1,25">弹幕</d></i>'),
        ("xml", '<!DOCTYPE x [<!ENTITY e "text">]><transcript><text start="0" dur="1">&e;</text></transcript>'),
        ("xml", "<html><body>login</body></html>"),
        ("srv2", '<timedtext><body><p t="0" d="1">字</p></body></timedtext>'),
        ("srt", "1\n00:00:01,000 --> 00:00:02,000\n字\n\nbroken block"),
        ("srt", "1\n00:00:03,000 --> 00:00:02,000\n字"),
        ("vtt", "WEBVTT\n\n00:00.000 --> 00:01.000\n字\n\n00:xx.000 --> 00:02.000\n丢失"),
        ("vtt", "WEBVTT\n\n00:61.000 --> 00:62.000\n字"),
        ("json3", {"events": [{"tStartMs": "NaN", "segs": [{"utf8": "字"}]}]}),
        ("bilibili-json", {"body": [{"from": 0, "to": float("inf"), "content": "字"}]}),
        ("whisper-json", {"segments": [{"start": 0, "end": 1, "text": None}]}),
        ("json", {"body": []}),
        ("unsupported", "字"),
        ("tsv", "start\tend\ttext\n0\t1\t字\textra"),
    ],
)
def test_invalid_data_never_becomes_missing_captions(fmt, body):
    with pytest.raises(ContractError):
        convert_captions(CaptionAcquisition(status="ready", payload=CaptionPayload(format=fmt, body=body)))


@pytest.mark.parametrize(
    "body",
    [
        '<transcript><text start="0" dur="1">字 &amp; 句</text></transcript>',
        '<timedtext><text t="0" d="1000">字 &amp; 句</text></timedtext>',
        '<timedtext><body><p t="0" d="1000">字 &amp; 句</p></body></timedtext>',
        '<tt><body><p begin="0s" dur="1s">字 &amp; 句</p></body></tt>',
    ],
)
def test_xml_dispatches_by_actual_root_structure(body):
    assert values(parse("xml", body)) == [(0, 1000, "字 & 句")]


def test_txt_has_no_invented_timestamps_and_can_roundtrip():
    segments = parse("txt", "第一行\n第二行\n重复\n重复")
    assert values(segments) == [(None, None, "第一行\n第二行\n重复\n重复")]
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"))
    document = TranscriptDocument(status="ready", segments=segments)
    transcript = render_transcript(item, document)
    assert "无时间轴" in transcript and "00:00:00" not in transcript
    restored = parse_transcript_markdown(transcript, TranscriptManifest(status="ready"))
    assert values(restored.segments) == values(segments)
    assert "第一行\n第二行\n重复\n重复" in render_context(item, document)
    with pytest.raises(InputError, match="时间轴"):
        filter_promotions(item, document, automatic=False, ranges=[(0, 1)])


def test_legacy_cache_is_explicitly_converted():
    data = {
        "status": "ready",
        "language": "zh",
        "source": "official",
        "segments": [{"segment_id": "seg-000001", "start_ms": 1200, "end_ms": 2500, "text": "旧字幕"}],
    }
    acquired = CaptionAcquisition.model_validate(data)
    assert acquired.payload.format == "soota-segments"
    assert values(convert_captions(acquired).segments) == [(1200, 2500, "旧字幕")]
    assert data.get("payload") is None


def test_source_format_not_provider_controls_conversion():
    class Provider:
        def __init__(self, name):
            self.name, self.saved = name, None

        def get_captions(self, item):
            return CaptionAcquisition(
                status="ready",
                payload=CaptionPayload(format="vtt", body="WEBVTT\n\n00:00.123 --> 00:01.234\n同一份字幕"),
            )

        def cache_captions(self, item, result):
            self.saved = result

    providers = [Provider("existing"), Provider("future-provider")]
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"))
    assert [values(acquire_captions(p, item).segments) for p in providers] == [[(123, 1234, "同一份字幕")]] * 2
    assert all(p.saved.payload.format == "vtt" for p in providers)


def test_providers_have_no_subtitle_conversion_dependencies():
    root = Path(__file__).parents[2] / "src" / "soota" / "providers"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(
            name.startswith(("soota.transcripts.formats", "soota.transcripts.conversion", "soota.transcripts.captions"))
            for name in imports
        ), path
        assert not any(isinstance(node, ast.Name) and node.id == "TranscriptSegment" for node in ast.walk(tree)), path


@pytest.mark.parametrize(
    "body", [" hello ", "第一行\n\n第二行\n", "\n\n重复\n重复\n\n", "<a id=x></a>\n## seg-not-a-header"]
)
def test_transcript_protocol_preserves_body_whitespace(body):
    import tempfile

    from soota.models import ContentBundleManifest
    from soota.render.bundle import _source_changed

    segments = parse("txt", body)
    document = TranscriptDocument(status="ready", segments=segments)
    item = MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001"))
    text = render_transcript(item, document)
    manifest = ContentBundleManifest(source=item.source, transcript=TranscriptManifest(status="ready"))
    restored = parse_transcript_markdown(text, manifest.transcript)
    assert values(restored.segments) == values(segments)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "transcript.md"
        path.write_text(text)
        assert not _source_changed(path, manifest, document)


@pytest.mark.parametrize("name", ["opencli", "opencli-mcp", "yt-dlp", "tikhub"])
def test_raw_caption_cache_preserves_body_and_expiry(settings, monkeypatch, name):
    from soota.providers.opencli import OpenCLIProvider
    from soota.providers.opencli_mcp import OpenCLIMCPProvider
    from soota.providers.tikhub.client import TikHubProvider
    from soota.providers.ytdlp import YtDlpProvider
    from soota.storage.cache import CacheStore

    settings.opencli_mcp.enabled = True
    if name == "tikhub":
        provider = TikHubProvider(cache=CacheStore(settings.cache_dir / "test-tikhub"), api_key="synthetic")
    else:
        provider = {"opencli": OpenCLIProvider, "opencli-mcp": OpenCLIMCPProvider, "yt-dlp": YtDlpProvider}[name](
            settings
        )
    source = recognize("https://www.bilibili.com/video/BV1xx411c7mD")
    item = MediaItem(source=source)
    raw = CaptionAcquisition(
        status="ready",
        language="zh",
        source="official",
        payload=CaptionPayload(
            format="srt",
            body="1\n00:00:00,000 --> 00:00:01,000\nhttps://example.invalid/?token=example123\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\n第二段不能被截断",
        ),
    )
    provider.cache_captions(item, raw)
    cached_files = list(provider.cache.root.rglob("captions*.json"))
    original_bytes = {p: p.read_bytes() for p in cached_files}
    result = acquire_captions(provider, item)
    assert values(result.segments) == [
        (0, 1000, "https://example.invalid/?token=example123"),
        (1000, 2000, "第二段不能被截断"),
    ]
    assert {p: p.read_bytes() for p in cached_files} == original_bytes
    assert provider.records[-1].cache_hit


def test_malformed_acquisition_cannot_be_cached():
    class Provider:
        def get_captions(self, item):
            return CaptionAcquisition(status="ready", payload=CaptionPayload(format="vtt", body="broken"))

        def cache_captions(self, item, result):
            pytest.fail("unvalidated subtitle must not be cached")

    with pytest.raises(ContractError):
        acquire_captions(Provider(), MediaItem(source=recognize("https://www.youtube.com/watch?v=Example0001")))


def test_whisper_tsv_quotes_are_literal_and_cannot_swallow_rows():
    body = 'start\tend\ttext\n1234\t2345\t"你好"\n2345\t3456\t"未闭合\n3456\t4567\t下一句\n'
    assert values(parse("tsv", body)) == [(1234, 2345, '"你好"'), (2345, 3456, '"未闭合'), (3456, 4567, "下一句")]


@pytest.mark.parametrize("attrs,metric", [("", "f"), ('xmlns:ttp="urn:example" ttp:tickRate="3"', "t")])
def test_ttml_exact_integer_times_do_not_lose_a_millisecond(attrs, metric):
    count = 30 if metric == "f" else 3
    body = f'<tt {attrs}><body><p begin="{count}{metric}" dur="{count}{metric}">字</p></body></tt>'
    assert values(parse("ttml", body)) == [(1000, 2000, "字")]


def test_srv1_decodes_legacy_double_escaped_entities_only_once_more():
    body = '<transcript><text start="0" dur="1">It&amp;#39;s good &amp;amp; fine.</text></transcript>'
    assert parse("srv1", body)[0].text == "It's good & fine."
    assert parse("srv2", '<timedtext><text t="0" d="1">&amp;amp;</text></timedtext>')[0].text == "&amp;"


@pytest.mark.parametrize("attribute", ['timeContainer="seq"', 'repeatCount="2"'])
def test_ttml_dynamic_attributes_in_nested_span_are_rejected(attribute):
    with pytest.raises(ContractError):
        parse("ttml", f'<tt><body><p dur="2s"><span {attribute}>字</span></p></body></tt>')


def test_vtt_missing_cue_separator_cannot_reassign_text_to_wrong_time():
    body = "WEBVTT\n\n00:00.000 --> 00:01.000\n第一句\n00:01.000 --> 00:02.000\n第二句"
    with pytest.raises(ContractError):
        parse("vtt", body)
