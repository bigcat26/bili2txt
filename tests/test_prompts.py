"""prompts：jinja2 模板渲染。"""

import pytest

from bili2txt.prompts import (
    DEFAULT_STYLE,
    STYLES,
    render_prompt,
    render_system_prompt,
)
from bili2txt.stages.download import VideoMeta
from bili2txt.stages.transcribe import Transcript


@pytest.fixture
def meta():
    return VideoMeta(
        video_id="BV1",
        title="测试标题",
        duration=120,
        uploader="UP主",
        webpage_url="http://x",
    )


@pytest.fixture
def transcript():
    return Transcript(language="zh", duration=120.0, text="转写正文内容", segments=[])


@pytest.mark.parametrize("style", STYLES)
def test_render_prompt_contains_vars(style, meta, transcript):
    out = render_prompt(style, meta, transcript)
    assert "测试标题" in out
    assert "UP主" in out
    assert "转写正文内容" in out


def test_render_prompt_invalid_style_falls_back(meta, transcript):
    out = render_prompt("nonexistent", meta, transcript)
    # 回落到 default 模板（含 TL;DR 标记）
    assert "TL;DR" in out


def test_render_system_prompt():
    assert "内容编辑" in render_system_prompt()


def test_render_prompt_custom_template(tmp_path, meta, transcript):
    tpl = tmp_path / "custom.j2"
    tpl.write_text("CUSTOM {{ title }} | {{ transcript }}", encoding="utf-8")
    out = render_prompt(DEFAULT_STYLE, meta, transcript, template_path=tpl)
    assert out == "CUSTOM 测试标题 | 转写正文内容"


def test_render_system_prompt_custom_template(tmp_path):
    tpl = tmp_path / "sys.j2"
    tpl.write_text("你是测试系统", encoding="utf-8")
    assert render_system_prompt(template_path=tpl) == "你是测试系统"


def test_render_prompt_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        render_prompt(DEFAULT_STYLE, None, None, template_path="/no/such/file.j2")
