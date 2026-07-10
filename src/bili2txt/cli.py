"""CLI 入口：bili2txt <BV/URL> [options]"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from . import __version__
from .cache import Cache, delete_video, list_videos
from .config import CONFIG
from .prompts import STYLES
from .stages.download import (
    VideoMeta,
    download_video,
    extract_video_id,
    fetch_video_info,
    normalize_url,
)
from .stages.extract import extract_audio
from .stages.summarize import summarize
from .stages.transcribe import Transcript, TranscriptSegment, transcribe

console = Console()


def video_hash_key(video_id: str) -> str:
    return f"bv_{video_id}"


def _stage_download(cache, normalized_url, vhash, force):
    if not cache.has(vhash, "download") or force:
        console.print(f"\n[bold cyan]① 下载视频[/bold cyan]  [dim]({vhash})[/dim]")
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      TimeElapsedColumn(), console=console, transient=True) as p:
            p.add_task("yt-dlp 下载中...", total=None)
            video_path, meta = download_video(
                normalized_url, vhash, cache, CONFIG.ytdlp_cookies, CONFIG.download_quality)
        console.print(f"  OK {meta.title}")
        size_mb = video_path.stat().st_size // 1024 // 1024
        console.print(f"  OK {video_path.relative_to(CONFIG.project_root)}  ({size_mb} MB)")
    else:
        out = cache.get_output(vhash, "download")
        console.print(f"[green]① 下载视频 命中缓存[/green]  {out.relative_to(CONFIG.project_root)}")
        mp = cache.meta_path(vhash, "download")
        extra = json.loads(mp.read_text(encoding="utf-8")).get("extra", {})
        meta = VideoMeta(
            video_id=extra["video_id"],
            title=extra["title"],
            duration=extra["duration"],
            uploader=extra["uploader"],
            webpage_url=extra["webpage_url"],
        )
        video_path = out
    return video_path, meta


def _stage_extract(cache, video_path, vhash, force):
    if not cache.has(vhash, "extract") or force:
        console.print(f"\n[bold cyan]② 抽音频 wav[/bold cyan]")
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      TimeElapsedColumn(), console=console, transient=True) as p:
            p.add_task("ffmpeg 抽音中...", total=None)
            wav = extract_audio(video_path, vhash, cache)
        size_mb = wav.stat().st_size // 1024 // 1024
        console.print(f"  OK {wav.relative_to(CONFIG.project_root)}  ({size_mb} MB)")
    else:
        wav = cache.get_output(vhash, "extract")
        console.print(f"[green]② 抽音频 命中缓存[/green]  {wav.relative_to(CONFIG.project_root)}")
    return wav


def _stage_transcribe(cache, wav, vhash, force):
    if not cache.has(vhash, "transcribe") or force:
        console.print(f"\n[bold cyan]③ 转写 (Whisper {CONFIG.whisper_model})[/bold cyan]")
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      TimeElapsedColumn(), console=console, transient=True) as p:
            p.add_task("语音转文字中（首次会下载模型）...", total=None)
            transcript = transcribe(wav, vhash, cache, CONFIG)
        console.print(f"  OK 语言: {transcript.language}  时长: {transcript.duration:.0f}s  "
                      f"段数: {len(transcript.segments)}  字数: {len(transcript.text)}")
        console.print(f"\n[dim]前 300 字预览：[/dim]")
        preview = transcript.text[:300] + ("..." if len(transcript.text) > 300 else "")
        console.print(preview)
    else:
        transcript = transcribe(wav, vhash, cache, CONFIG)
        preview = transcript.text[:300] + ("..." if len(transcript.text) > 300 else "")
        console.print(f"[green]③ 转写 命中缓存[/green]  {preview}")
    return transcript


def _stage_summarize(cache, transcript, meta, vhash, template_path=None):
    if not CONFIG.llm_api_key:
        console.print("\n[yellow]④ 跳过 LLM 总结：未配置 LLM_API_KEY[/yellow]")
        console.print("[dim]复制 .env.example 为 .env 并填 LLM_API_KEY，再去掉 --skip summarize 即可调用。[/dim]")
        return None

    if cache.has(vhash, "summarize"):
        cached_md = cache.get_output(vhash, "summarize")
        console.print(f"[green]④ LLM 总结 命中缓存[/green]  {cached_md.relative_to(CONFIG.project_root)}")
        return cached_md.read_text(encoding="utf-8")

    console.print(f"\n[bold cyan]④ LLM 总结[/bold cyan]  [dim]({CONFIG.llm_model})[/dim]")
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  TimeElapsedColumn(), console=console, transient=True) as p:
        p.add_task("LLM 生成总结中...", total=None)
        summary = summarize(transcript, meta, vhash, cache, CONFIG, template_path)

    console.print(f"\n[bold green]OK 总结完成[/bold green]")
    out_path = CONFIG.output_dir / f"{meta.video_id}_{meta.display_title}.md"
    console.print(f"  -> {out_path.relative_to(CONFIG.project_root)}")
    console.print(f"\n[dim]--- 总结预览 ---[/dim]")
    preview = summary[:600] + ("..." if len(summary) > 600 else "")
    console.print(preview)
    return summary


def cmd_info(args):
    target = normalize_url(args.url_or_id)
    console.print(f"[dim]Fetching info for {target} ...[/dim]")
    meta, _raw = fetch_video_info(target, CONFIG.ytdlp_cookies)
    console.print(f"\n[bold]{meta.title}[/bold]\n")
    console.print(f"  ID:       {meta.video_id}")
    console.print(f"  UP:       {meta.uploader}")
    console.print(f"  Duration: {meta.duration // 60}m{meta.duration % 60}s ({meta.duration}s)")
    console.print(f"  URL:      {meta.webpage_url}")
    if meta.description and meta.description != "-":
        desc = meta.description[:500]
        suffix = "..." if len(meta.description) > 500 else ""
        console.print(f"\n[dim]{desc}{suffix}[/dim]")


# ---------- 独立 stage 入口（本地文件） ----------
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac"}
VIDEO_EXT = {".mp4", ".mkv", ".flv", ".webm", ".mov", ".avi", ".ts"}


def _local_audio_hash(path: Path) -> str:
    """本地音频/视频文件的缓存 key：(大小, mtime, 头 1KB 内容) 的 hash。"""
    import hashlib
    h = hashlib.sha256()
    st = path.stat()
    h.update(f"{st.st_size}:{int(st.st_mtime)}:".encode())
    with path.open("rb") as f:
        h.update(f.read(1024))
    return f"local_{path.suffix.lstrip('.')}_{h.hexdigest()[:16]}"


def _load_transcript_json(path: Path):
    """从 .json 转写文件读出 Transcript 对象。"""
    from .stages.transcribe import Transcript, TranscriptSegment
    data = json.loads(path.read_text(encoding="utf-8"))
    return Transcript(
        language=data["language"],
        duration=data["duration"],
        text=data["text"],
        segments=[TranscriptSegment(**s) for s in data["segments"]],
    )


def cmd_transcribe_file(args):
    """bili2txt transcribe <file> — 直接转写本地音/视频文件。"""
    from .stages.transcribe import transcribe as do_transcribe, FasterWhisperTranscriber

    src = Path(args.file).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"文件不存在：{src}")

    # 视频文件 → 先抽音；纯音频 → 直接用
    if src.suffix.lower() in VIDEO_EXT:
        wav_dir = src.parent / f".{src.stem}_bili2txt_wav"
        wav_dir.mkdir(exist_ok=True)
        wav = wav_dir / "audio.wav"
        if not wav.exists():
            console.print(f"[dim]检测到视频格式，先抽音到 {wav} ...[/dim]")
            import subprocess
            subprocess.check_call([
                "ffmpeg", "-y", "-i", str(src),
                "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
                str(wav),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        audio_path = wav
    elif src.suffix.lower() in AUDIO_EXT:
        audio_path = src
    else:
        raise ValueError(f"不支持的格式：{src.suffix}（支持音频 {AUDIO_EXT} / 视频 {VIDEO_EXT}）")

    # 临时覆盖 model / language
    if args.model or args.language:
        from dataclasses import replace
        global CONFIG
        overrides = {}
        if args.model:
            overrides["whisper_model"] = args.model
        if args.language:
            overrides["whisper_language"] = args.language
        CONFIG = replace(CONFIG, **overrides)

    # 转写（直接调函数，不走 cache hash 链）
    console.print(f"[bold cyan]③ 转写[/bold cyan]  [dim]{src.name}  (Whisper {CONFIG.whisper_model})[/dim]")
    transcriber = FasterWhisperTranscriber(CONFIG)
    transcript = transcriber.transcribe(audio_path, language=CONFIG.whisper_language)

    # 输出
    out_txt = Path(args.out) if args.out else src.with_suffix(".transcript.txt")
    out_json = out_txt.with_suffix(".json")
    out_txt.write_text(transcript.text, encoding="utf-8")
    out_json.write_text(json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    console.print(f"  ✓ 语言: {transcript.language}  时长: {transcript.duration:.0f}s  "
                  f"段数: {len(transcript.segments)}  字数: {len(transcript.text)}")
    console.print(f"  → {out_txt}")
    console.print(f"  → {out_json}")
    if transcript.text:
        console.print(f"\n[dim]前 300 字预览：[/dim]")
        console.print(transcript.text[:300] + ("..." if len(transcript.text) > 300 else ""))


def cmd_extract_file(args):
    """bili2txt extract <file> — 视频/音频 → wav（跳过 yt-dlp 下载）。"""
    src = Path(args.file).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"文件不存在：{src}")

    cache = Cache()
    vhash = _local_audio_hash(src)
    wav = extract_audio(src, vhash, cache)

    out = Path(args.out) if args.out else src.with_suffix(".wav")
    if out.resolve() != wav.resolve():
        shutil.copy(wav, out)
    console.print(f"  ✓ 已抽出音频：{out}")
    console.print(f"  → {out}")


def cmd_summarize_file(args):
    """bili2txt summarize <file> — 转写文本 → LLM 总结（跳过 ASR）。"""
    global CONFIG
    if getattr(args, "style", None):
        CONFIG = replace(CONFIG, summary_style=args.style)

    src = Path(args.file).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"文件不存在：{src}")

    # 支持 .json 转写文件，也支持纯文本
    try:
        transcript = _load_transcript_json(src)
    except (json.JSONDecodeError, KeyError):
        transcript = Transcript(
            language="zh",
            duration=0.0,
            text=src.read_text(encoding="utf-8"),
            segments=[],
        )

    vhash = _local_audio_hash(src)
    meta = VideoMeta(
        video_id=args.title or src.stem,
        title=args.title or src.stem,
        duration=0,
        uploader=args.uploader or "-",
        webpage_url="",
    )

    console.print(f"[bold cyan]④ LLM 总结[/bold cyan]  [dim]({CONFIG.llm_model})[/dim]")
    summary = summarize(transcript, meta, vhash, Cache(), CONFIG, getattr(args, "template", None))

    out = Path(args.out) if args.out else src.with_suffix(".summary.md")
    out.write_text(summary, encoding="utf-8")
    console.print(f"  → {out}")
    if summary:
        console.print(f"\n[dim]预览：[/dim]")
        console.print(summary[:600] + ("..." if len(summary) > 600 else ""))


def cmd_pipeline(args):
    cache = Cache()
    only = args.only
    skip = set(args.skip or [])
    force = args.force

    # --style 覆盖默认总结风格；--quality 覆盖默认下载清晰度
    global CONFIG
    if getattr(args, "style", None):
        CONFIG = replace(CONFIG, summary_style=args.style)
    if getattr(args, "quality", None):
        CONFIG = replace(CONFIG, download_quality=args.quality)
    template_path = getattr(args, "template", None)

    normalized_url = normalize_url(args.url_or_id)
    try:
        video_id = extract_video_id(normalized_url)
    except ValueError:
        console.print("[dim]URL 中没识别到 BV 号，先抓元数据...[/dim]")
        meta, _ = fetch_video_info(normalized_url, CONFIG.ytdlp_cookies)
        video_id = meta.video_id

    vhash = video_hash_key(video_id)

    if force:
        d = cache.video_dir(vhash)
        if d.exists():
            shutil.rmtree(d)
            console.print(f"[yellow]已清空缓存：{d}[/yellow]")

    video_path, meta = _stage_download(cache, normalized_url, vhash, force)
    if only == "download":
        return

    wav = _stage_extract(cache, video_path, vhash, force)
    if only == "extract":
        return

    transcript = _stage_transcribe(cache, wav, vhash, force)
    if only == "transcribe":
        return

    if "summarize" in skip:
        console.print("\n[yellow]④ 已跳过总结 (--skip summarize)[/yellow]")
        return

    _stage_summarize(cache, transcript, meta, vhash, template_path)


def cmd_list(args):
    cache = Cache()
    if not cache.root.exists():
        console.print("[yellow]还没有任何缓存[/yellow]")
        return
    dirs = sorted([d for d in cache.root.iterdir() if d.is_dir()])
    if not dirs:
        console.print("[yellow]还没有任何缓存[/yellow]")
        return
    console.print(f"\n[bold]已处理视频 ({len(dirs)} 个)[/bold]\n")
    for d in dirs:
        first_meta = json_load_first(d)
        if first_meta:
            console.print(f"[bold cyan]{first_meta.get('extra', {}).get('title', d.name)}[/bold cyan]")
            console.print(f"  {d.name}  -> {d.relative_to(CONFIG.project_root)}")
            for m in sorted(d.glob("*/meta.json")):
                stage = m.parent.name
                extra_size = ""
                if stage == "download":
                    sz = first_meta.get("extra", {}).get("size_bytes", 0)
                    extra_size = f"  ({sz // 1024 // 1024} MB)"
                elif stage == "transcribe":
                    cnt = first_meta.get("extra", {}).get("segment_count", "")
                    extra_size = f"  ({cnt} segments)" if cnt else ""
                console.print(f"  + [green]OK[/green] {stage}{extra_size}")
            console.print()


def json_load_first(video_dir):
    for stage in ("download", "extract", "transcribe", "summarize"):
        mp = video_dir / stage / "meta.json"
        if mp.exists():
            try:
                return json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


# ---------- cleanup ----------
def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _list_hf_models() -> list[dict]:
    """列 HF 缓存里的模型。"""
    out: list[dict] = []
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        for repo in info.repos:
            if repo.repo_type != "model":
                continue
            size = sum(s.size_on_disk for s in repo.revisions[0].files) if repo.revisions else 0
            out.append({
                "repo_id": repo.repo_id,
                "size_bytes": repo.size_on_disk,
                "revisions": len(repo.revisions),
                "last_modified": max((r.last_modified for r in repo.revisions), default=None),
            })
    except Exception:
        pass
    return out


def _delete_hf_model(repo_id: str) -> bool:
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        for repo in info.repos:
            if repo.repo_id == repo_id and repo.repo_type == "model":
                info.delete_revisions(*[r.commit_id for r in repo.revisions]).execute()
                return True
    except Exception:
        pass
    return False


def cmd_cleanup(args):
    """清理模型缓存 / 视频产物。默认 dry-run。"""
    import shutil
    targets_models = args.cleanup_models or args.cleanup_all
    targets_cache = args.cleanup_cache or args.cleanup_all
    if not (targets_models or targets_cache):
        targets_models = True   # 默认行为：什么都不传时列全部
        targets_cache = True

    console.print("[bold]🧹 Cleanup 预览（dry-run，加 --force 才真删）[/bold]\n")

    # ---- 模型 ----
    if targets_models:
        models = _list_hf_models()
        # 也看 modelscope 的缓存
        ms_root = Path.home() / ".cache" / "modelscope" / "hub"
        ms_models: list[dict] = []
        if ms_root.exists():
            for d in ms_root.iterdir():
                if d.is_dir():
                    size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
                    ms_models.append({"path": d, "size": size, "name": d.name})

        if not models and not ms_models:
            console.print("[dim]HF / modelscope 缓存里没有模型[/dim]")
        else:
            console.print(f"[bold cyan]模型缓存[/bold cyan]")
            for m in sorted(models, key=lambda x: -x["size_bytes"]):
                last = m["last_modified"].strftime("%Y-%m-%d %H:%M") if m["last_modified"] else "?"
                console.print(f"  [green]HF[/green] {m['repo_id']:<48} {_fmt_size(m['size_bytes']):>10}  {last}")
            for m in sorted(ms_models, key=lambda x: -x["size"]):
                console.print(f"  [magenta]MS[/magenta] {m['name']:<48} {_fmt_size(m['size']):>10}")
            total = sum(m["size_bytes"] for m in models) + sum(m["size"] for m in ms_models)
            console.print(f"  [dim]合计: {_fmt_size(total)}[/dim]\n")

    # ---- 视频缓存 ----
    if targets_cache:
        videos = list_videos()
        if not videos:
            console.print("[dim]没有已处理的视频[/dim]")
        else:
            # 按 mtime 排序，最新在前
            videos.sort(key=lambda v: -v["mtime"])
            keep_n = args.keep_last or 0
            console.print(f"[bold cyan]视频产物 ({len(videos)} 个)[/bold cyan]" +
                          (f"  [dim]--keep-last {keep_n}，保留最新 {min(keep_n, len(videos))} 个[/dim]"
                           if keep_n else ""))
            for i, v in enumerate(videos):
                # keep_n > 0 且 i < keep_n 则保留
                mark = "[green]KEEP[/green]" if (keep_n and i < keep_n) else "[yellow]DROP[/yellow]"
                import datetime
                ts = datetime.datetime.fromtimestamp(v["mtime"]).strftime("%Y-%m-%d %H:%M")
                console.print(f"  {mark}  {v['hash']:<22} {_fmt_size(v['size_bytes']):>10}  "
                              f"{ts}  {v['title'][:40]}")
            if not args.force:
                console.print(f"\n[dim]确认删除加 --force[/dim]")
            console.print()

    if not args.force:
        return

    # ---- 真删 ----
    if args.force:
        deleted = []
        if targets_models:
            for m in models if targets_models else []:
                if _delete_hf_model(m["repo_id"]):
                    deleted.append(f"HF:{m['repo_id']}")
            for m in ms_models:
                try:
                    shutil.rmtree(m["path"])
                    deleted.append(f"MS:{m['name']}")
                except Exception:
                    pass
        if targets_cache:
            keep_n = args.keep_last or 0
            for i, v in enumerate(videos):
                if keep_n and i < keep_n:
                    continue
                if delete_video(v["hash"]):
                    deleted.append(f"cache:{v['hash']}")

        if deleted:
            console.print(f"[green]✓ 已删：[/green]")
            for d in deleted:
                console.print(f"  - {d}")
        else:
            console.print("[dim]没删任何东西[/dim]")


def build_parser():
    p = argparse.ArgumentParser(
        prog="bili2txt",
        description="B 站视频 → 音频 → 文字 → LLM 总结",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  bili2txt https://www.bilibili.com/video/BV1xx411c7mD
  bili2txt BV1xx411c7mD
  bili2txt BV1xx411c7mD --only transcribe
  bili2txt BV1xx411c7mD --skip summarize --whisper-model small
  bili2txt BV1xx411c7mD --quality 720

  bili2txt transcribe ./audio.wav
  bili2txt transcribe ./video.mp4 --model small
  bili2txt extract ./video.mp4 --out ./audio.wav
  bili2txt summarize ./transcript.txt --style bullets

  bili2txt --info BV1xx411c7mD
  bili2txt --list
  bili2txt --cleanup --cache --keep-last 3
""",
    )
    p.add_argument("-V", "--version", action="version", version=f"bili2txt {__version__}")
    p.add_argument("url_or_id", nargs="?", help="BV 号 / av 号 / B 站完整 URL")
    p.add_argument("--only",
                   choices=["download", "extract", "transcribe"],
                   help="只跑到指定阶段就停（不调用 LLM）")
    p.add_argument("--skip", nargs="*", choices=["summarize"], default=[],
                   help="跳过某些阶段（目前仅支持 summarize）")
    p.add_argument("--force", action="store_true",
                   help="忽略缓存，强制重跑所有阶段")
    p.add_argument("--whisper-model", help="覆盖 WHISPER_MODEL 环境变量")
    p.add_argument("--quality", choices=["audio", "360", "480", "720", "1080", "best"],
                   help="下载清晰度（默认 audio 仅音频，最省带宽；总结场景够用）")
    p.add_argument("--style", choices=STYLES,
                   help="总结风格（覆盖 SUMMARY_STYLE）")
    p.add_argument("--template", help="自定义 jinja2 总结模板路径，覆盖内置模板")
    p.add_argument("--info", dest="info_target", metavar="URL",
                   help="只看视频元信息，不下载（例: --info BV1xx...）")
    p.add_argument("--list", dest="list_cache", action="store_true",
                   help="列出已处理的视频")
    # cleanup 标志
    p.add_argument("--cleanup", dest="do_cleanup", action="store_true",
                   help="清理模型缓存 / 视频产物（默认 dry-run，加 --force 真删）")
    p.add_argument("--models", dest="cleanup_models", action="store_true",
                   help="配合 --cleanup：只清模型")
    p.add_argument("--cache", dest="cleanup_cache", action="store_true",
                   help="配合 --cleanup：只清视频产物")
    p.add_argument("--all", dest="cleanup_all", action="store_true",
                   help="配合 --cleanup：模型+视频产物全清")
    p.add_argument("--keep-last", type=int, default=0, metavar="N",
                   help="配合 --cleanup --cache：保留最近 N 个视频产物")
    return p


def build_subparser(sub_name: str) -> argparse.ArgumentParser:
    """给 subcommand 各自一个独立 parser，绕开顶层 url_or_id 冲突。"""
    p = argparse.ArgumentParser(
        prog=f"bili2txt {sub_name}",
        description={
            "transcribe": "bili2txt transcribe <file> — 音/视频 → 文字（跳过 yt-dlp 下载）",
            "extract": "bili2txt extract <file> — 视频 → wav（跳过 yt-dlp 下载）",
            "summarize": "bili2txt summarize <file> — 转写文本 → LLM 总结（跳过 ASR）",
        }[sub_name],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("file", help="本地文件路径")
    if sub_name == "transcribe":
        p.add_argument("--model", help="Whisper 模型（覆盖 WHISPER_MODEL）")
        p.add_argument("--language", help="强制指定语言，如 zh/en/ja")
        p.add_argument("--out", help="输出 .txt 路径，默认 ./<file_stem>.transcript.txt")
    elif sub_name == "extract":
        p.add_argument("--out", help="输出 wav 路径，默认 ./<file_stem>.wav")
    elif sub_name == "summarize":
        p.add_argument("--style", choices=["default", "bullets", "academic", "casual"],
                       help="总结风格（覆盖 SUMMARY_STYLE）")
        p.add_argument("--template", help="自定义 jinja2 总结模板路径，覆盖内置模板")
        p.add_argument("--title", help="视频标题（写到总结 markdown 头部）")
        p.add_argument("--uploader", help="UP 主（写到总结 markdown 头部）")
        p.add_argument("--out", help="输出 markdown 路径，默认 ./<file_stem>.summary.md")
    return p


SUBCOMMANDS = {"transcribe", "extract", "summarize"}


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # 手动分发 subcommand（避开 argparse subparsers 跟顶层 url_or_id 的冲突）
    if argv and argv[0] in SUBCOMMANDS:
        sub_name = argv[0]
        sub_args = argv[1:]
        sub_parser = build_subparser(sub_name)
        sub_parsed = sub_parser.parse_args(sub_args)
        try:
            if sub_name == "transcribe":
                return cmd_transcribe_file(sub_parsed) or 0
            elif sub_name == "extract":
                return cmd_extract_file(sub_parsed) or 0
            elif sub_name == "summarize":
                return cmd_summarize_file(sub_parsed) or 0
        except KeyboardInterrupt:
            console.print("\n[yellow]已取消[/yellow]")
            return 130
        except Exception as e:
            console.print(f"\n[red]FAIL: [/red] {e}")
            if "--debug" in argv:
                raise
            return 1

    # 主流程
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_cache:
        return cmd_list(args) or 0
    if args.info_target:
        args.url_or_id = args.info_target
        return cmd_info(args) or 0
    if args.do_cleanup:
        return cmd_cleanup(args) or 0

    if not args.url_or_id:
        parser.print_help()
        return 1

    if args.whisper_model:
        from dataclasses import replace
        global CONFIG
        CONFIG = replace(CONFIG, whisper_model=args.whisper_model)

    try:
        cmd_pipeline(args)
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]已取消[/yellow]")
        return 130
    except Exception as e:
        console.print(f"\n[red]FAIL: [/red] {e}")
        if "--debug" in sys.argv:
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
