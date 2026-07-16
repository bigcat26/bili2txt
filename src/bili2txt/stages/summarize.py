"""Stage 5 — LLM 总结。"""

from __future__ import annotations

import re
from pathlib import Path

from openai import OpenAI

from ..cache import Cache
from ..config import Config
from ..prompts import render_prompt, render_system_prompt
from .transcribe import Transcript

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think_block(text: str) -> str:
    """去掉带思考模式模型（如 MiniMax-M3）输出中的 <think>...</think> 块。"""
    return _THINK_BLOCK_RE.sub("", text).strip()


def summarize(
    transcript: Transcript,
    video_meta,                    # VideoMeta
    video_hash: str,
    cache: Cache,
    cfg: Config,
    template_path: str | Path | None = None,
) -> str:
    """调用 LLM 生成总结，写 markdown 到 cache + data/output。"""
    cached = cache.get_output(video_hash, "summarize")
    if cached:
        return cached.read_text(encoding="utf-8")

    if not cfg.llm_api_key:
        raise RuntimeError(
            "LLM_API_KEY 未配置。复制 .env.example 为 .env 并填上 key。\n"
            "如果不想用 LLM，可以跳过 --only transcribe，只看转写结果。"
        )

    client = OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)
    system_prompt = render_system_prompt(template_path)
    prompt = render_prompt(cfg.summary_style, video_meta, transcript, template_path)

    resp = client.chat.completions.create(
        model=cfg.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    summary = _strip_think_block((resp.choices[0].message.content or "").strip())

    # 写两份：
    # 1. cache 里给流水线用
    stage_dir = cache.stage_dir(video_hash, "summarize")
    cache_md = stage_dir / "summary.md"
    cache_md.write_text(summary, encoding="utf-8")
    cache.write_meta(video_hash, "summarize", cache_md, {
        "model": cfg.llm_model,
        "style": cfg.summary_style,
        "input_chars": len(transcript.text),
    })

    # 2. output 里给用户看：filename = <video_id>_<title>.md
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out_md = cfg.output_dir / f"{video_meta.video_id}_{video_meta.display_title}.md"
    header = (
        f"# {video_meta.title}\n\n"
        f"> **BV**: [{video_meta.video_id}]({video_meta.webpage_url})  \n"
        f"> **UP**: {video_meta.uploader}  \n"
        f"> **时长**: {video_meta.duration // 60}m{video_meta.duration % 60}s  \n"
        f"> **语言**: {transcript.language}\n\n"
        f"---\n\n"
    )
    out_md.write_text(header + summary, encoding="utf-8")
    return summary