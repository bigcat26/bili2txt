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


def ensure_model(model_name: str, local_dir: Path | None = None) -> str:
    """确保模型在本地可用。返回模型路径（本地目录）。

    - 如果 model_name 已经是本地路径，直接返回
    - 否则尝试 modelscope 下载（国内可用），失败时回退到 huggingface_hub
    """
    p = Path(model_name).expanduser()
    if p.exists() and (p / "config.json").exists():
        return str(p)

    target = local_dir or (Path.home() / ".cache" / "bili2txt" / "models" / model_name)
    target = Path(target)
    if (target / "config.json").exists():
        return str(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from modelscope import snapshot_download
        downloaded = snapshot_download(f"Systran/{model_name}", cache_dir=str(target.parent))
        # modelscope 返回的是 snapshots/master 路径，里面有 config.json
        return downloaded
    except Exception as e:
        # 回退到 huggingface_hub（需要能访问 huggingface.co / HF_ENDPOINT）
        from huggingface_hub import snapshot_download as hf_snapshot
        if "HF_ENDPOINT" not in os.environ:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        return hf_snapshot(repo_id=f"Systran/{model_name}", cache_dir=str(target.parent))


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