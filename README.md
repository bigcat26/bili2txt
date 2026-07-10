# bili2txt

**你是我的眼, 带我阅读浩瀚的视频世界**

B 站视频 → 音频 → 文字 → LLM 总结，一条命令搞定。

```
B站链接 → 下载视频(yt-dlp) → 抽音频(wav) → Whisper → LLM总结
   ①           ②             ③          ④        ⑤
```

## 安装

```bash
# 需要：python ≥ 3.13, ffmpeg, uv（推荐）
brew install ffmpeg
brew install uv

git clone <repo> bili2txt && cd bili2txt
uv sync

cp .env.example .env   # 然后填 LLM_API_KEY
```

## 用法

```bash
# 全流程
uv run bili2txt https://www.bilibili.com/video/BV1xx411c7mD

# 只跑到转写（不花钱）
uv run bili2txt BV1xx411c7mD --only transcribe

# 跳过 LLM 总结，但跑其他全流程
uv run bili2txt BV1xx411c7mD --skip summarize

# 强制重跑（清掉缓存）
uv run bili2txt BV1xx411c7mD --force

# 看视频元信息（不下、不转、不总结）
uv run bili2txt info BV1xx411c7mD

# 列出已处理的视频
uv run bili2txt list

# 批量跑：videos.txt 每行一个 BV / av / 完整 URL（空行 / # 注释 / 重复自动跳过）
uv run bili2txt batch videos.txt
# 只跑到转写，遇错即停
uv run bili2txt batch videos.txt --only transcribe --stop-on-error
# 走管道
cat videos.txt | uv run bili2txt batch -
# 并发 3（Whisper 抢 CPU 资源，默认 1 串行更稳）
uv run bili2txt batch videos.txt -j 3
# 不写汇总报告
uv run bili2txt batch videos.txt --no-report
# 报告写到指定文件
uv run bili2txt batch videos.txt --report ./batch_log.md
```

### 批量输入文件格式（`videos.txt`）

```
# 这是注释，会被忽略
BV1uoME6xEGp
BV1koT46eEJY  # 行内注释（两个空格 + #）
av12345
https://www.bilibili.com/video/BV1hETj6SEze

BV1uoME6xEGp   # 重复会被去重，不会跑两遍
乱七八糟的垃圾行   # 非 BV/av/URL 直接忽略
```

每行一条，支持 `BV` 号 / `av` 号 / 完整 B 站 URL。空行、`#` 开头注释、行内 `  #` 注释、重复项、非法行 都会自动跳过并在汇总里报告 `跳过 N`。

### 批量结果

任务结束时会输出汇总（成功/失败数 + 用时 + 失败明细），并默认把报告写到 `bili2txt_batch_report_<时间>.md`，表格里列出每条状态、用时、错误信息。失败不会阻塞后续任务；加 `--stop-on-error` 可在首个失败时中止。

## 配置

所有配置在 `.env` 里：

| 变量 | 说明 | 默认 |
|---|---|---|
| `WHISPER_MODEL` | faster-whisper 模型大小 | `base` |
| `WHISPER_DEVICE` | `auto` / `cpu` / `cuda` | `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` / `float16` / `float32` | `int8` |
| `WHISPER_LANGUAGE` | 强制语言（留空自动检测） | 空 |
| `LLM_BASE_URL` | OpenAI 兼容接口 base URL | `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | API key | 必填 |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `SUMMARY_STYLE` | `default` / `bullets` / `academic` / `casual` | `default` |
| `YTDLP_COOKIES` | cookies.txt 路径（会员画质需要） | 空 |

### Whisper 模型选择

| 模型 | 大小 | 速度 | 准确度 |
|---|---|---|---|
| `tiny` | ~75 MB | ⚡⚡⚡ | ⭐ |
| `base` | ~150 MB | ⚡⚡ | ⭐⭐ |
| `small` | ~500 MB | ⚡ | ⭐⭐⭐ |
| `medium` | ~1.5 GB | 🐢 | ⭐⭐⭐⭐ |
| `large-v3` | ~3 GB | 🐢🐢 | ⭐⭐⭐⭐⭐ |

macOS / CPU 推荐 `base` 或 `small`，跑得动且质量够用。

### LLM 推荐

- **deepseek-chat** — 中文最强 / 最便宜（百万 token ~ 2 元），首选
- **siliconflow Qwen2.5-32B** — 备选，国产开源
- **gpt-4o-mini** — 英文场景 / 多模态好
- **ollama 本地 qwen2.5** — 完全离线（需要本地 GPU）

## 架构

```
src/bili2txt/
├── cli.py               # CLI 入口
├── config.py            # .env + 环境变量加载
├── cache.py             # 内容 hash 缓存
├── prompts.py           # 总结 prompt 风格模板
└── stages/
    ├── download.py      # ② yt-dlp 下载
    ├── extract.py       # ③ ffmpeg 抽 wav
    ├── transcribe.py    # ④ faster-whisper（抽象基类，可换 FunASR）
    └── summarize.py     # ⑤ OpenAI 兼容 LLM
```

每个 stage 的产物都落盘到 `data/cache/<bv_xxx>/<stage>/`，重复跑同一个视频秒出。

## 替换 ASR 引擎

`src/bili2txt/stages/transcribe.py` 定义了抽象基类 `Transcriber`：

```python
class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, wav_path: Path, language: str | None = None) -> Transcript: ...
```

实现一个 `FunASRTranscriber(Transcriber)`，在 `transcribe()` 里跑 FunASR 返回 `Transcript`，然后在 CLI 里注入即可。

## 已知限制 / 待加

- 登录态 / 会员画质需要导出 cookies.txt 填 `YTDLP_COOKIES`
- 分 P 视频只处理第一 P（其他分 P 改 URL）
- 没做字幕弹幕优先策略（先转写音频，后续可加 `yt-dlp --write-subs` 跳过 ASR）
- LLM 没有长文分段总结（超过模型 context 会截断，目前 prompt 里有压缩提示）

## License

MIT
