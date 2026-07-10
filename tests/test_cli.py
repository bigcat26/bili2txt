"""cli：子命令分发 + 此前缺失的 extract/summarize 子命令（回归）。"""

import pytest

import bili2txt.cli as cli
from bili2txt.cache import Cache
from bili2txt.config import Config
from dataclasses import replace


def test_local_audio_hash_deterministic(tmp_path):
    f = tmp_path / "a.wav"
    f.write_bytes(b"data")
    assert cli._local_audio_hash(f) == cli._local_audio_hash(f)
    g = tmp_path / "b.wav"
    g.write_bytes(b"other")
    assert cli._local_audio_hash(f) != cli._local_audio_hash(g)


def test_subcommand_functions_defined():
    # 回归：此前 cmd_extract_file / cmd_summarize_file 被引用但从未定义
    assert callable(cli.cmd_extract_file)
    assert callable(cli.cmd_summarize_file)


def test_main_summarize_subcommand(monkeypatch, tmp_path):
    import bili2txt.stages.summarize as sm

    class _Msg:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = _Msg(c)

    class _Resp:
        def __init__(self, c):
            self.choices = [_Choice(c)]

    class _Completions:
        def create(self, **kw):
            return _Resp("## 总结\n来自子命令的总结")

    class _Chat:
        completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, *a, **k):
            self.chat = _Chat()

    monkeypatch.setattr(sm, "OpenAI", _FakeOpenAI)

    # 让子命令用临时 cache / output
    cfg = replace(Config.load(), llm_api_key="x", output_dir=tmp_path)
    monkeypatch.setattr(cli, "CONFIG", cfg)
    monkeypatch.setattr(cli, "Cache", lambda *a, **k: Cache(root=tmp_path))

    transcript_file = tmp_path / "t.txt"
    transcript_file.write_text("子命令用的转写文本", encoding="utf-8")
    out = tmp_path / "result.summary.md"

    rc = cli.main(["summarize", str(transcript_file), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert "来自子命令的总结" in out.read_text(encoding="utf-8")


def test_main_help_without_args(capsys):
    rc = cli.main([])
    assert rc == 1
    out = capsys.readouterr().out
    assert "bili2txt" in out
