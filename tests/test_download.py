"""download 阶段：BV/av/URL 解析等纯函数。"""

import pytest

from bili2txt.stages.download import (
    VideoMeta,
    build_format,
    extract_video_id,
    normalize_url,
)


@pytest.mark.parametrize("inp,expected", [
    ("BV1bHTD61EZW", "BV1bHTD61EZW"),
    ("https://www.bilibili.com/video/BV1bHTD61EZW", "BV1bHTD61EZW"),
    ("https://www.bilibili.com/video/BV1bHTD61EZW?t=30", "BV1bHTD61EZW"),
    ("av12345", "av12345"),
    ("https://www.bilibili.com/video/av12345", "av12345"),
])
def test_extract_video_id(inp, expected):
    assert extract_video_id(inp) == expected


def test_extract_video_id_invalid():
    with pytest.raises(ValueError):
        extract_video_id("not a video link at all")


@pytest.mark.parametrize("inp,expected", [
    ("BV1bHTD61EZW", "https://www.bilibili.com/video/BV1bHTD61EZW"),
    ("av12345", "https://www.bilibili.com/video/av12345"),
    ("https://www.bilibili.com/video/BV1x", "https://www.bilibili.com/video/BV1x"),
])
def test_normalize_url(inp, expected):
    assert normalize_url(inp) == expected


@pytest.mark.parametrize("quality,expected", [
    ("audio", "ba/bestaudio"),
    ("best", "bv*+ba/b"),
    ("360", "bv[height<=360]+ba/b"),
    ("1080", "bv[height<=1080]+ba/b"),
    ("weird", "bv*+ba/b"),
])
def test_build_format(quality, expected):
    assert build_format(quality) == expected


def test_video_meta_display_title_sanitized():
    m = VideoMeta(
        video_id="BV1",
        title='标题/带:非法*字符?\\"',
        duration=100,
        uploader="up",
        webpage_url="http://x",
    )
    # 非法文件名字符应被替换
    assert "/" not in m.display_title
    assert ":" not in m.display_title
    assert m.display_title.startswith("标题")
