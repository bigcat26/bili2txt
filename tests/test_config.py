"""config / 纯函数层测试：无需网络、ffmpeg、LLM。"""

from bili2txt.config import Config


def test_config_defaults_without_env(monkeypatch):
    # 清掉可能从 .env 注入的变量，验证默认值
    for k in ("WHISPER_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "SUMMARY_STYLE"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config.load()
    assert cfg.whisper_model == "base"
    assert cfg.llm_base_url == "https://api.deepseek.com/v1"
    assert cfg.llm_model == "deepseek-chat"
    assert cfg.summary_style == "default"
    assert cfg.cache_dir.name == "cache"
    assert cfg.output_dir.name == "output"
