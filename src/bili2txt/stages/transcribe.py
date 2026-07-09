"""Stage 4 — 语音转文字。

默认实现：faster-whisper（CTranslate2，本地 CPU/MPS）。
预留接口位 FunASR / OpenAI Whisper API / 其他。
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path

from ..cache import Cache
from ..config import Config


def resolve_repo_id(model_name: str) -> str:
    """把用户写的短名 / 长名统一成 HF repo_id。

    接受:
      - "base"                         → "Systran/faster-whisper-base"
      - "faster-whisper-base"          → "Systran/faster-whisper-base"
      - "Systran/faster-whisper-base"  → "Systran/faster-whisper-base"
      - "guillaumekln/faster-whisper"  → 原样返回
    """
    if "/" in model_name:
        # 已经是 owner/name 形式
        if model_name.startswith("faster-whisper-"):
            return f"Systran/{model_name}"
        return model_name
    if not model_name.startswith("faster-whisper-"):
        return f"Systran/faster-whisper-{model_name}"
    return f"Systran/{model_name}"


def ensure_model(model_name: str) -> str:
    """确保模型在本地可用。返回模型快照目录路径。

    优先级：本地路径 > huggingface_hub (HF_ENDPOINT 默认 hf-mirror.com 国内加速)
             > modelscope 兜底（镜像文件 hash 可能跟 HF 不完全一致，加载可能报校验错）

    模型缓存路径：~/.cache/huggingface/hub/models--{owner}--{name}/snapshots/<rev>/
    （huggingface_hub 默认路径，跟 `huggingface-cli` 兼容，方便 cleanup）
    """
    # 1) 本地路径直传
    p = Path(model_name).expanduser()
    if p.exists() and (p / "config.json").exists():
        return str(p)

    repo_id = resolve_repo_id(model_name)

    # 2) 检查 HF 缓存是否已经下过
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        for repo in info.repos:
            if repo.repo_id == repo_id and repo.repo_type == "model":
                # 找最新 revision 的 snapshot
                revisions = sorted(repo.revisions, key=lambda r: r.last_modified, reverse=True)
                if revisions:
                    snap_path = str(revisions[0].snapshot_path)
                    if Path(snap_path, "config.json").exists():
                        return snap_path
    except Exception:
        pass

    # 3) 走 HF 下载
    hf_endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ["HF_ENDPOINT"] = hf_endpoint
    # 国内 hf-mirror.com 上 xet 链路不稳，关掉走普通 HTTP
    os.environ.setdefault("USE_HF_XET", "0")
    try:
        from huggingface_hub import snapshot_download as hf_snapshot
        return hf_snapshot(repo_id=repo_id, cache_dir=None)  # None = 用 HF 默认缓存
    except Exception as e:
        # 4) HF 不通时，modelscope 兜底（仅建议在 tiny/base/small 用，large 系列可能 hash 不一致）
        try:
            from modelscope import snapshot_download as ms_snapshot
            return ms_snapshot(repo_id=repo_id)
        except Exception:
            raise RuntimeError(
                f"无法下载模型 {repo_id}（HF endpoint={hf_endpoint} 不通，modelscope 也失败）。\n"
                f"原始错误: {e}\n"
                f"试试手动下载后用本地路径：WHISPER_MODEL=/path/to/model"
            ) from e


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Transcript:
    language: str
    duration: float
    text: str
    segments: list[TranscriptSegment]

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "duration": self.duration,
            "text": self.text,
            "segments": [s.to_dict() for s in self.segments],
        }


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, wav_path: Path, language: str | None = None) -> Transcript: ...


class FasterWhisperTranscriber(Transcriber):
    """faster-whisper 实现（CTranslate2 后端）。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            device = self.cfg.whisper_device
            if device == "auto":
                device = "cpu"  # macOS MPS 暂不完全稳定，CPU + int8 最稳
            model_path = ensure_model(self.cfg.whisper_model)
            self._model = WhisperModel(
                model_path,
                device=device,
                compute_type=self.cfg.whisper_compute_type,
            )
        return self._model

    def transcribe(self, wav_path: Path, language: str | None = None) -> Transcript:
        model = self._load()
        segs, info = model.transcribe(
            str(wav_path),
            language=language,
            vad_filter=True,         # 过滤静音段，提速
            vad_parameters={"min_silence_duration_ms": 500},
            beam_size=5,
            best_of=5,
        )
        segments: list[TranscriptSegment] = []
        text_parts: list[str] = []
        for seg in segs:
            t = seg.text.strip()
            segments.append(TranscriptSegment(start=seg.start, end=seg.end, text=t))
            text_parts.append(t)
        return Transcript(
            language=info.language,
            duration=info.duration,
            text=" ".join(text_parts).strip(),
            segments=segments,
        )


def transcribe(
    wav_path: Path,
    video_hash: str,
    cache: Cache,
    cfg: Config,
    transcriber: Transcriber | None = None,
) -> Transcript:
    """转写 + 缓存。返回 Transcript。"""
    cached = cache.get_output(video_hash, "transcribe")
    if cached:
        # 缓存的 transcript 以 .json 形式存，文本本体放 .txt 方便人类读
        json_path = cached
        transcript = Transcript(**{
            k: ([TranscriptSegment(**s) for s in v] if k == "segments" else v)
            for k, v in json.loads(json_path.read_text(encoding="utf-8")).items()
        })
        return transcript

    if transcriber is None:
        transcriber = FasterWhisperTranscriber(cfg)

    transcript = transcriber.transcribe(wav_path, language=cfg.whisper_language)

    stage_dir = cache.stage_dir(video_hash, "transcribe")
    json_path = stage_dir / "transcript.json"
    txt_path = stage_dir / "transcript.txt"
    json_path.write_text(
        json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(transcript.text, encoding="utf-8")

    cache.write_meta(video_hash, "transcribe", json_path, {
        "language": transcript.language,
        "duration": transcript.duration,
        "segment_count": len(transcript.segments),
    })
    return transcript