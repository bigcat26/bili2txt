"""内容哈希缓存：同一个视频重跑时跳过已完成的 stage。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import CONFIG


@dataclass
class StageMeta:
    """单个 stage 的元数据 + 输出路径。"""

    stage: str
    output: str           # 相对 cache_dir 的路径
    extra: dict          # 其他字段（如 transcript 的 segment 数、duration 等）
    finished_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class Cache:
    """基于内容 hash 的 stage 缓存。

    命名约定：cache/<video_hash>/<stage>/<output>
    每个 stage 自己决定 hash key（视频 hash / 音频 hash / 转写参数 hash）。
    """

    def __init__(self, root: Path | None = None):
        self.root = root or CONFIG.cache_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def video_dir(self, video_hash: str) -> Path:
        d = self.root / video_hash
        d.mkdir(parents=True, exist_ok=True)
        return d

    def stage_dir(self, video_hash: str, stage: str) -> Path:
        d = self.video_dir(video_hash) / stage
        d.mkdir(parents=True, exist_ok=True)
        return d

    def meta_path(self, video_hash: str, stage: str) -> Path:
        return self.stage_dir(video_hash, stage) / "meta.json"

    def has(self, video_hash: str, stage: str) -> bool:
        return self.meta_path(video_hash, stage).exists()

    def write_meta(self, video_hash: str, stage: str, output: Path, extra: dict | None = None):
        meta = StageMeta(
            stage=stage,
            output=str(output.relative_to(self.root / video_hash)),
            extra=extra or {},
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.meta_path(video_hash, stage).write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_output(self, video_hash: str, stage: str) -> Path | None:
        mp = self.meta_path(video_hash, stage)
        if not mp.exists():
            return None
        meta = json.loads(mp.read_text(encoding="utf-8"))
        p = self.root / video_hash / meta["output"]
        return p if p.exists() else None


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def hash_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()[:16]


# ---------- cleanup ----------
def list_videos(root: Path | None = None) -> list[dict]:
    """列出 cache 下所有视频产物，返回 [{hash, title, size_bytes, mtime, stages: [...]}, ...]。"""
    root = root or CONFIG.cache_dir
    if not root.exists():
        return []
    out: list[dict] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        # 读 download stage 的 meta（最权威的标题）
        title = d.name
        size_bytes = 0
        mtime = d.stat().st_mtime
        stages: list[str] = []
        for stage_dir in sorted(d.iterdir()):
            if not stage_dir.is_dir():
                continue
            stages.append(stage_dir.name)
            for p in stage_dir.rglob("*"):
                if p.is_file():
                    size_bytes += p.stat().st_size
            mp = stage_dir / "meta.json"
            if mp.exists():
                try:
                    import json
                    extra = json.loads(mp.read_text(encoding="utf-8")).get("extra", {})
                    if "title" in extra and extra["title"]:
                        title = extra["title"]
                except Exception:
                    pass
        out.append({
            "hash": d.name,
            "title": title,
            "size_bytes": size_bytes,
            "mtime": mtime,
            "stages": stages,
        })
    return out


def delete_video(video_hash: str, root: Path | None = None) -> bool:
    """删某个视频的所有 stage。返回是否真删了。"""
    import shutil
    root = root or CONFIG.cache_dir
    d = root / video_hash
    if d.exists() and d.is_dir():
        shutil.rmtree(d)
        return True
    return False