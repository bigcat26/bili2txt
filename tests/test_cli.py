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


# ---------- batch ----------

def test_batch_subcommand_registered():
    assert "batch" in cli.SUBCOMMANDS
    assert callable(cli.cmd_batch)


def test_read_batch_lines_parses_file(tmp_path):
    f = tmp_path / "v.txt"
    f.write_text(
        "# 一堆 BV 号\n"
        "BV1GJ411x7h7\n"
        "\n"
        "  BV1Eb4y1Q7GD  # 注释\n"
        "av12345\n"
        "https://www.bilibili.com/video/BV1GJ411x7h7\n"
        "BV1GJ411x7h7\n"   # 重复
        "乱七八糟的垃圾行\n"
    )
    items, src, skipped, total = cli._read_batch_lines(str(f))
    assert total == 8
    # 跳过：注释行 + 空行 + 重复 BV + 垃圾行 = 4
    assert skipped == 4
    assert items == [
        "BV1GJ411x7h7",
        "BV1Eb4y1Q7GD",
        "av12345",
        "https://www.bilibili.com/video/BV1GJ411x7h7",
    ]
    assert src == str(f)


def test_read_batch_lines_stdin(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(sys, "stdin", type("S", (), {
        "read": staticmethod(lambda: "BV1GJ411x7h7\n\n# 注释\nav7\n")
    })())
    items, src, skipped, total = cli._read_batch_lines("-")
    assert src == "<stdin>"
    assert total == 4
    assert skipped == 2
    assert items == ["BV1GJ411x7h7", "av7"]


def test_read_batch_lines_missing_file():
    with pytest.raises(FileNotFoundError):
        cli._read_batch_lines("/nonexistent/path.txt")


def test_read_batch_lines_empty():
    import sys
    class _S:
        def read(self):
            return ""
    real = sys.stdin
    sys.stdin = _S()
    try:
        items, src, skipped, total = cli._read_batch_lines("-")
    finally:
        sys.stdin = real
    assert items == []
    assert total == 0


def test_cmd_batch_empty_input(tmp_path, capsys):
    f = tmp_path / "empty.txt"
    f.write_text("\n\n# 注释\n垃圾行\n")
    rc = cli.main(["batch", str(f)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "没有有效条目" in out


def test_cmd_batch_runs_pipeline_with_error_isolation(monkeypatch, tmp_path):
    """每个条目单独调 cmd_pipeline；单条失败不阻塞其他；产出汇总。"""
    calls: list[str] = []
    failures = {"BV1Eb4y1Q7GD"}   # 模拟其中一个炸

    def fake_pipeline(args):
        calls.append(args.url_or_id)
        if args.url_or_id in failures:
            raise RuntimeError("yt-dlp 404")

    monkeypatch.setattr(cli, "cmd_pipeline", fake_pipeline)

    # 让 cache / output 都指向 tmp_path
    cfg = replace(Config.load(), output_dir=tmp_path)
    monkeypatch.setattr(cli, "CONFIG", cfg)
    monkeypatch.setattr(cli, "Cache", lambda *a, **k: Cache(root=tmp_path))

    f = tmp_path / "v.txt"
    f.write_text(
        "BV1GJ411x7h7\n"
        "BV1Eb4y1Q7GD\n"
        "BV1eJ411x7wE\n"
    )
    rc = cli.main(["batch", str(f), "--no-report"])
    assert rc == 1  # 有失败 → 非零退出
    assert calls == ["BV1GJ411x7h7", "BV1Eb4y1Q7GD", "BV1eJ411x7wE"]


def test_cmd_batch_stop_on_error(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_pipeline(args):
        calls.append(args.url_or_id)
        if args.url_or_id == "BV1Eb4y1Q7GD":
            raise RuntimeError("boom")

    monkeypatch.setattr(cli, "cmd_pipeline", fake_pipeline)
    cfg = replace(Config.load(), output_dir=tmp_path)
    monkeypatch.setattr(cli, "CONFIG", cfg)
    monkeypatch.setattr(cli, "Cache", lambda *a, **k: Cache(root=tmp_path))

    f = tmp_path / "v.txt"
    f.write_text("BV1GJ411x7h7\nBV1Eb4y1Q7GD\nBV1eJ411x7wE\n")
    rc = cli.main(["batch", str(f), "--stop-on-error", "--no-report"])
    assert rc == 1
    assert calls == ["BV1GJ411x7h7", "BV1Eb4y1Q7GD"]   # 第三个没跑


def test_cmd_batch_writes_report(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "cmd_pipeline", lambda args: None)  # 全成功
    cfg = replace(Config.load(), output_dir=tmp_path, project_root=tmp_path)
    monkeypatch.setattr(cli, "CONFIG", cfg)
    monkeypatch.setattr(cli, "Cache", lambda *a, **k: Cache(root=tmp_path))

    f = tmp_path / "v.txt"
    f.write_text("BV1GJ411x7h7\nBV1Eb4y1Q7GD\n")
    report = tmp_path / "r.md"
    rc = cli.main(["batch", str(f), "--report", str(report)])
    assert rc == 0
    text = report.read_text(encoding="utf-8")
    assert "bili2txt 批量任务报告" in text
    assert "BV1GJ411x7h7" in text
    assert "BV1Eb4y1Q7GD" in text
    assert "成功**: 2" in text


def test_cmd_batch_dedupes_input(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(cli, "cmd_pipeline", lambda args: calls.append(args.url_or_id) or None)
    cfg = replace(Config.load(), output_dir=tmp_path)
    monkeypatch.setattr(cli, "CONFIG", cfg)
    monkeypatch.setattr(cli, "Cache", lambda *a, **k: Cache(root=tmp_path))

    f = tmp_path / "v.txt"
    f.write_text("BV1GJ411x7h7\nBV1GJ411x7h7\nBV1Eb4y1Q7GD\n")
    rc = cli.main(["batch", str(f), "--no-report"])
    assert rc == 0
    assert calls == ["BV1GJ411x7h7", "BV1Eb4y1Q7GD"]


def test_read_batch_lines_handles_real_list_file(tmp_path):
    """回归：跟项目根的 ./list 文件结构保持一致。"""
    f = tmp_path / "list"
    f.write_text(
        "BV1GJ411x7h7\n"
        "BV1UT42167xb\n"
    )
    items, src, skipped, total = cli._read_batch_lines(str(f))
    assert total == 15
    assert skipped == 0
    assert len(items) == 15


def test_short_err_strips_calledprocesserror():
    """回归：CalledProcessError 里整条命令会被贴到 str(e)，要截断成简短形式。"""
    long_err = (
        "CalledProcessError: Command '['/opt/homebrew/bin/yt-dlp', "
        "'-f', 'ba/bestaudio', '--merge-output-format', 'mp4', "
        "'-o', './data/cache/bv_xxx/download/%(id)s.%(ext)s', "
        "'--no-playlist', '--no-overwrites', '--write-info-json', "
        "'https://www.bilibili.com/video/BV1xxx']' returned non-zero exit status 1."
    )
    out = cli._short_err(long_err)
    assert "yt-dlp 失败" in out
    assert "exit=1" in out
    # 不能把整条命令贴出来
    assert "merge-output-format" not in out
    assert "--write-info-json" not in out
    assert len(out) < 80




def test_short_err_passthrough_short():
    assert cli._short_err("ValueError: bad") == "ValueError: bad"


def test_short_err_truncates_long():
    long_msg = "RuntimeError: " + "x" * 1000
    out = cli._short_err(long_msg)
    assert len(out) < 220
    assert out.endswith("…")


def test_cmd_batch_failure_shows_error_inline(monkeypatch, tmp_path, capsys):
    """回归：单条失败时，✗ 行后必须紧跟简短错误（不然用户 Ctrl+C 拿不到原因）。"""
    def fake_pipeline(args):
        raise RuntimeError("yt-dlp 失败 something")

    monkeypatch.setattr(cli, "cmd_pipeline", fake_pipeline)
    cfg = replace(Config.load(), output_dir=tmp_path, project_root=tmp_path)
    monkeypatch.setattr(cli, "CONFIG", cfg)
    monkeypatch.setattr(cli, "Cache", lambda *a, **k: Cache(root=tmp_path))

    f = tmp_path / "v.txt"
    f.write_text("BV1GJ411x7h7\n")
    rc = cli.main(["batch", str(f), "--no-report", "--stop-on-error"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "✗" in out
    # 错误信息要当场打印出来，不只在最后汇总
    assert "yt-dlp 失败 something" in out
