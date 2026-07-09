"""Stage 3 — ffmpeg 从视频抽 16kHz 单声道 wav。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..cache import Cache, hash_file


def extract_audio(
    video_path: Path,
    video_hash: str,
    cache: Cache,
) -> Path:
    """抽出 16kHz mono PCM wav — Whisper 推荐输入格式。"""
    if not shutil_which("ffmpeg"):
        raise RuntimeError("ffmpeg 不在 PATH 中，先 brew install ffmpeg")

    stage_dir = cache.stage_dir(video_hash, "extract")
    out_wav = stage_dir / "audio.wav"

    # 命中缓存：比对源视频 hash
    meta = cache.get_output(video_hash, "extract")
    if meta and meta.exists():
        cached_hash = cache.meta_path(video_hash, "extract").read_text(encoding="utf-8")
        # 简化：只要 wav 文件存在就直接复用，省 hash 校验
        if 'video_hash' in cached_hash and video_hash in cached_hash:
            return meta

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",                  # 不要视频流
        "-ac", "1",             # 单声道
        "-ar", "16000",         # 16kHz 采样率
        "-acodec", "pcm_s16le", # 16-bit PCM
        str(out_wav),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    extra = {
        "video_hash": video_hash,
        "size_bytes": out_wav.stat().st_size,
        "duration_estimate_sec": None,  # 可选：用 ffprobe 取
    }
    cache.write_meta(video_hash, "extract", out_wav, extra)
    return out_wav


def shutil_which(cmd: str) -> str | None:
    import shutil
    return shutil.which(cmd)