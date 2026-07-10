"""config / 纯函数层测试：无需网络、ffmpeg、LLM。"""

from bili2txt.config import Config


def test_config_defaults_without_env(monkeypatch, tmp_path):
    # 让 Config.load 读取一个不存在的 .env，避免项目里真实的 .env 干扰默认值验证
    monkeypatch.setattr("bili2txt.config.ENV_FILE", tmp_path / "no_such.env")
    for k in ("WHISPER_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "SUMMARY_STYLE", "DOWNLOAD_QUALITY"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config.load()
    assert cfg.whisper_model == "base"
    assert cfg.llm_base_url == "https://api.deepseek.com/v1"
    assert cfg.llm_model == "deepseek-chat"
    assert cfg.summary_style == "default"
    assert cfg.download_quality == "audio"
    assert cfg.cache_dir.name == "cache"
    assert cfg.output_dir.name == "output"
