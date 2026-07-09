"""集中加载配置：env 文件 + 环境变量 + 默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：bili2txt 包所在目录的再上一级
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Config:
    # paths
    project_root: Path
    data_dir: Path
    cache_dir: Path
    output_dir: Path

    # yt-dlp
    ytdlp_cookies: Path | None

    # whisper
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    whisper_language: str | None

    # llm
    llm_base_url: str
    llm_api_key: str | None
    llm_model: str

    # summary
    summary_style: str

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(ENV_FILE)

        data_dir = PROJECT_ROOT / "data"
        cookies_raw = os.getenv("YTDLP_COOKIES", "").strip()
        cookies = Path(cookies_raw).expanduser() if cookies_raw else None

        return cls(
            project_root=PROJECT_ROOT,
            data_dir=data_dir,
            cache_dir=data_dir / "cache",
            output_dir=data_dir / "output",
            ytdlp_cookies=cookies if cookies and cookies.exists() else None,
            whisper_model=os.getenv("WHISPER_MODEL", "base"),
            whisper_device=os.getenv("WHISPER_DEVICE", "auto"),
            whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            whisper_language=os.getenv("WHISPER_LANGUAGE", "").strip() or None,
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip() or None,
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
            summary_style=os.getenv("SUMMARY_STYLE", "default"),
        )


# 单例
CONFIG = Config.load()