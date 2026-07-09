"""Stage 2 — yt-dlp 下载 B 站视频。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..cache import Cache, hash_file


def _find_ytdlp() -> str:
    """优先用 PATH 里的 yt-dlp，否则用 venv 里的。"""
    p = shutil.which("yt-dlp")
    if p:
        return p
    # uv venv 在项目根的 .venv/bin/yt-dlp
    candidates = [
        Path(sys.executable).parent / "yt-dlp",
        Path(__file__).resolve().parents[3] / ".venv" / "bin" / "yt-dlp",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    raise RuntimeError("找不到 yt-dlp 二进制。运行 `uv sync` 或 `pip install yt-dlp`")


@dataclass
class VideoMeta:
    video_id: str       # BV 号或 av 号
    title: str
    duration: int       # 秒
    uploader: str
    webpage_url: str
    description: str = ""

    @property
    def display_title(self) -> str:
        # 用于文件名 / 输出报告，去掉控制字符
        return re.sub(r"[\\/:*?\"<>|\n\r\t]", "_", self.title)[:120]


_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"(av\d+)", re.I)


def extract_video_id(url_or_id: str) -> str:
    """支持 BV 号 / av 号 / 完整 URL / 短链。返回视频 ID。"""
    s = url_or_id.strip()
    m = _BV_RE.search(s)
    if m:
        return m.group(1)
    m = _AV_RE.search(s)
    if m:
        return m.group(1)
    if s.startswith("http"):
        return s  # 让 yt-dlp 自己解析
    raise ValueError(f"无法从 {url_or_id!r} 中识别 BV 号或 av 号")


def normalize_url(url_or_id: str) -> str:
    """把 BV 号 / av 号补成完整 URL；URL 直接返回。"""
    s = url_or_id.strip()
    if s.startswith("http"):
        return s
    if _BV_RE.fullmatch(s) or _BV_RE.match(s):
        return f"https://www.bilibili.com/video/{s}"
    if _AV_RE.fullmatch(s) or _AV_RE.match(s):
        return f"https://www.bilibili.com/video/{s}"
    # 兜底，让 yt-dlp 自己尝试
    return s


def fetch_video_info(url: str, cookies: Path | None = None) -> tuple[VideoMeta, dict]:
    """先 dump JSON 元数据，不下载。"""
    cmd = [
        _find_ytdlp(),
        "--dump-json",
        "--no-download",
        "--no-playlist",
        url,
    ]
    if cookies:
        cmd += ["--cookies", str(cookies)]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    # yt-dlp 会一次 dump 一个 JSON object（多视频时多行）；单视频只一行
    data = json.loads(out.strip().splitlines()[-1])
    meta = VideoMeta(
        video_id=data["id"],
        title=data.get("title", "untitled"),
        duration=int(data.get("duration") or 0),
        uploader=data.get("uploader") or data.get("channel") or "",
        webpage_url=data.get("webpage_url") or url,
        description=data.get("description", ""),
    )
    return meta, data


def download_video(
    url: str,
    video_hash: str,
    cache: Cache,
    cookies: Path | None = None,
) -> tuple[Path, VideoMeta]:
    """下载最佳 mp4 到 cache/<hash>/download/，返回 (视频路径, meta)。"""
    stage_dir = cache.stage_dir(video_hash, "download")
    outtmpl = str(stage_dir / "%(id)s.%(ext)s")

    cmd = [
        _find_ytdlp(),
        "-f", "bv*+ba/b",         # 最佳视频+音频，回退到最佳单文件
        "--merge-output-format", "mp4",
        "-o", outtmpl,
        "--no-playlist",
        "--no-overwrites",
        "--write-info-json",      # 写一份 .info.json，方便排查
        url,
    ]
    if cookies:
        cmd += ["--cookies", str(cookies)]

    subprocess.check_call(cmd)
    info_files = list(stage_dir.glob("*.info.json"))
    if not info_files:
        raise RuntimeError(f"下载完成但未找到 .info.json: {stage_dir}")

    info = json.loads(info_files[0].read_text(encoding="utf-8"))
    meta = VideoMeta(
        video_id=info["id"],
        title=info.get("title", "untitled"),
        duration=int(info.get("duration") or 0),
        uploader=info.get("uploader") or info.get("channel") or "",
        webpage_url=info.get("webpage_url") or url,
        description=info.get("description", ""),
    )

    video_files = [p for p in stage_dir.iterdir()
                   if p.suffix in {".mp4", ".mkv", ".webm", ".flv"} and not p.name.endswith(".part")]
    if not video_files:
        raise RuntimeError(f"下载目录里没找到视频文件: {stage_dir}")
    video_path = max(video_files, key=lambda p: p.stat().st_size)

    # 算 hash（基于文件内容）
    real_hash = hash_file(video_path)
    extra = {
        "video_id": meta.video_id,
        "title": meta.title,
        "uploader": meta.uploader,
        "duration": meta.duration,
        "webpage_url": meta.webpage_url,
        "size_bytes": video_path.stat().st_size,
        "content_hash": real_hash,
    }
    cache.write_meta(video_hash, "download", video_path, extra)
    return video_path, meta