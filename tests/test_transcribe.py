"""transcribe 阶段：模型名解析、Transcript 序列化、转写 JSON 读写。"""

import json

import pytest

from bili2txt.stages.transcribe import (
    Transcript,
    TranscriptSegment,
    resolve_repo_id,
)


@pytest.mark.parametrize("inp,expected", [
    ("base", "Systran/faster-whisper-base"),
    ("small", "Systran/faster-whisper-small"),
    ("faster-whisper-base", "Systran/faster-whisper-base"),
    ("Systran/faster-whisper-base", "Systran/faster-whisper-base"),
    ("guillaumekln/faster-whisper", "guillaumekln/faster-whisper"),
])
def test_resolve_repo_id(inp, expected):
    assert resolve_repo_id(inp) == expected


def test_transcript_to_dict_roundtrip():
    t = Transcript(
        language="zh",
        duration=12.5,
        text="hello world",
        segments=[TranscriptSegment(start=0.0, end=1.0, text="hello")],
    )
    d = t.to_dict()
    assert d["language"] == "zh"
    assert d["segments"][0]["text"] == "hello"
    t2 = Transcript(**{
        k: ([TranscriptSegment(**s) for s in v] if k == "segments" else v)
        for k, v in d.items()
    })
    assert t2.text == t.text
    assert t2.segments[0].end == 1.0


def test_load_transcript_json(tmp_path):
    from bili2txt.cli import _load_transcript_json

    data = {
        "language": "zh",
        "duration": 30.0,
        "text": "这是转写",
        "segments": [{"start": 0.0, "end": 2.0, "text": "这是转写"}],
    }
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    t = _load_transcript_json(p)
    assert isinstance(t, Transcript)
    assert t.text == "这是转写"
    assert t.segments[0].text == "这是转写"
