from soota.models import TranscriptSegment, TranscriptSource
from soota.transcripts.captions import merge_paragraphs, parse_bilibili_body, parse_srt


def test_parse_srt_assigns_stable_ids() -> None:
    text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n2\n00:00:01,000 --> 00:00:02,000\nWorld\n"
    segs = parse_srt(text, language="en", source=TranscriptSource.OFFICIAL)
    assert [s.segment_id for s in segs] == ["seg-000001", "seg-000002"]
    assert segs[0].text == "Hello"


def test_bilibili_body_not_danmaku() -> None:
    segs = parse_bilibili_body(
        {"body": [{"from": 0, "to": 1, "content": "字幕"}]},
        language="zh",
        source=TranscriptSource.OFFICIAL,
    )
    assert segs[0].text == "字幕"


def test_merge_paragraphs_drops_dense_clocks() -> None:
    segs = [
        TranscriptSegment(
            segment_id="seg-000001",
            start_ms=0,
            end_ms=800,
            text="谷歌",
            language="zh",
            source=TranscriptSource.ASR,
        ),
        TranscriptSegment(
            segment_id="seg-000002",
            start_ms=800,
            end_ms=1600,
            text="离职潮。",
            language="zh",
            source=TranscriptSource.ASR,
        ),
        TranscriptSegment(
            segment_id="seg-000003",
            start_ms=4000,
            end_ms=5000,
            text="下一句",
            language="zh",
            source=TranscriptSource.ASR,
        ),
    ]
    paras = merge_paragraphs(segs)
    assert paras == ["谷歌离职潮。", "下一句"]
