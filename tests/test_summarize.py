"""summarize 阶段：mock OpenAI，验证渲染 + 落盘。"""

from dataclasses import replace

import pytest

from bili2txt.cache import Cache
from bili2txt.config import Config
from bili2txt.stages.download import VideoMeta
from bili2txt.stages.summarize import summarize
from bili2txt.stages.transcribe import Transcript


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def create(self, **kwargs):
        # 校验 messages 结构：system + user
        msgs = kwargs["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "测试标题" in msgs[1]["content"]
        return _FakeResponse("## 总结\n这是总结内容")


class _FakeChat:
    completions = _FakeCompletions()


class _FakeOpenAI:
    def __init__(self, *a, **k):
        self.chat = _FakeChat()


@pytest.fixture
def cfg(tmp_path):
    base = Config.load()
    return replace(base, llm_api_key="test-key", output_dir=tmp_path, summary_style="default")


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


def test_summarize_writes_output(monkeypatch, tmp_path, cfg, meta, transcript):
    import bili2txt.stages.summarize as sm

    monkeypatch.setattr(sm, "OpenAI", _FakeOpenAI)
    cache = Cache(root=tmp_path)
    out = summarize(transcript, meta, "bv_test", cache, cfg)

    assert "这是总结内容" in out
    # 缓存 + 输出 markdown 都已写入
    assert cache.has("bv_test", "summarize")
    md = cfg.output_dir / "BV1_测试标题.md"
    assert md.exists()
    assert "这是总结内容" in md.read_text(encoding="utf-8")


def test_summarize_uses_custom_template(monkeypatch, tmp_path, cfg, meta, transcript):
    import bili2txt.stages.summarize as sm

    captured = {}

    class _FakeCompletions2:
        def create(self, **kwargs):
            captured["user"] = kwargs["messages"][1]["content"]
            return _FakeResponse("ok")

    class _FakeChat2:
        completions = _FakeCompletions2()

    class _FakeOpenAI2:
        def __init__(self, *a, **k):
            self.chat = _FakeChat2()

    monkeypatch.setattr(sm, "OpenAI", _FakeOpenAI2)
    tpl = tmp_path / "t.j2"
    tpl.write_text("TMPL {{ title }}", encoding="utf-8")

    summarize(transcript, meta, "bv_tpl", Cache(root=tmp_path), cfg, template_path=tpl)
    assert captured["user"] == "TMPL 测试标题"


def test_summarize_no_api_key_raises(tmp_path, meta, transcript):
    cfg = replace(Config.load(), llm_api_key=None)
    with pytest.raises(RuntimeError):
        summarize(transcript, meta, "bv_x", Cache(root=tmp_path), cfg)
