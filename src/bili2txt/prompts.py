"""总结 prompt 模板。"""

from __future__ import annotations

from .stages.transcribe import Transcript

# 风格定义：(system_hint, body_template)
# body_template 里可用占位符：{title} {uploader} {duration} {language} {transcript}

STYLES = {
    "default": (
        "默认风格：分章节 + 重点 + 行动项。",
        """请把下面这段 B 站视频的转写内容整理成结构化笔记。

# 视频元信息
- 标题: {title}
- UP主: {uploader}
- 时长: {duration} 秒
- 语言: {language}

# 输出格式（用 Markdown）
## TL;DR
三句话以内的核心结论。

## 分章节摘要
按主题 / 时间分段，每段 2-4 句。

## 关键观点
编号列表，5-10 条。

## 行动项 / 金句
如有可执行建议或值得反复看的金句，挑 3-5 条。

## 转写原文（如转写超过 8000 字，请压缩到 1500 字以内保留要点；否则原样输出）
<transcript>
{transcript}
</transcript>
""",
    ),
    "bullets": (
        "极简 bullet 风格：只保留关键信息。",
        """把下面视频压缩成 10 条以内的 bullet，不要展开，每条不超过一行。

## 视频
- {title} ({uploader}, {duration}s)

## 关键 bullet
1.
2.
...

## 转写
{transcript}
""",
    ),
    "academic": (
        "学术笔记风格：客观、结构化、引用原话。",
        """把下面这段内容写成学术风格的笔记。

# {title}
作者/UP主: {uploader} | 时长: {duration}s | 语言: {language}

## 摘要 (Abstract)
一段话概括主旨和方法。

## 核心论点
1. ...
2. ...

## 重要引述
> "..." — 时间戳 xx:xx

## 局限 / 待验证
如有存疑或未充分论证之处，单独列出。

## 转写原文
{transcript}
""",
    ),
    "casual": (
        "口语化聊天风：像朋友分享给我听。",
        """用聊天口吻给我讲讲这个视频说了啥，要点都用 bullet，但语气轻松。

视频: {title} ({uploader})

## 一句话总结
...

## 讲了啥
- ...

## 我可能想知道的
- ...

## 转写（保留主干）
{transcript}
""",
    ),
}


def render_prompt(style: str, video_meta, transcript: Transcript) -> str:
    if style not in STYLES:
        style = "default"
    _, body = STYLES[style]
    return body.format(
        title=video_meta.title,
        uploader=video_meta.uploader,
        duration=video_meta.duration,
        language=transcript.language,
        transcript=transcript.text,
    )