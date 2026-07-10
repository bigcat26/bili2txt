"""总结 prompt 模板（jinja2）。

模板文件放在本模块同级的 prompts/ 目录：
  - default.j2  / bullets.j2 / academic.j2 / casual.j2  —— 用户可见的总结正文
  - system.j2                                         —— 系统提示词

变量（user 模板可用）：
  title / uploader / duration / language / transcript

也可通过 render_prompt(template_path=...) / render_system_prompt(template_path=...)
传入自定义 .j2 文件，覆盖内置模板。
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from .stages.transcribe import Transcript

# 内置模板所在目录（与 prompts.py 同级）
PROMPTS_DIR = Path(__file__).parent / "prompts"

# 内置风格名（与 prompts/<name>.j2 对应）
STYLES = ("default", "bullets", "academic", "casual")

DEFAULT_STYLE = "default"


def _load(template_name: str) -> Template:
    path = PROMPTS_DIR / f"{template_name}.j2"
    if not path.exists():
        raise FileNotFoundError(f"找不到 prompt 模板：{path}")
    return Template(path.read_text(encoding="utf-8"))


def _load_path(template_path: str | Path) -> Template:
    path = Path(template_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到 prompt 模板：{path}")
    return Template(path.read_text(encoding="utf-8"))


def render_prompt(
    style: str,
    video_meta,
    transcript: Transcript,
    template_path: str | Path | None = None,
) -> str:
    """渲染用户可见的总结正文。

    - template_path 给定时，用该自定义模板；
    - 否则用 PROMPTS_DIR/<style>.j2，style 非法时回落到 default。
    """
    if template_path:
        tpl = _load_path(template_path)
    else:
        name = style if style in STYLES else DEFAULT_STYLE
        tpl = _load(name)

    return tpl.render(
        title=video_meta.title,
        uploader=video_meta.uploader,
        duration=video_meta.duration,
        language=transcript.language,
        transcript=transcript.text,
    )


def render_system_prompt(template_path: str | Path | None = None) -> str:
    """渲染系统提示词。"""
    if template_path:
        return _load_path(template_path).render()
    return _load("system").render()
