"""cache 阶段：hash 与 stage 读写。"""

from bili2txt.cache import Cache, hash_bytes, hash_file


def test_hash_bytes_deterministic():
    assert hash_bytes(b"abc") == hash_bytes(b"abc")
    assert hash_bytes(b"abc") != hash_bytes(b"def")


def test_hash_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    h1 = hash_file(f)
    assert isinstance(h1, str) and len(h1) == 16
    f.write_bytes(b"world")
    assert hash_file(f) != h1


def test_cache_write_get_has(tmp_path):
    cache = Cache(root=tmp_path)
    vh = "bv_test"
    out = cache.stage_dir(vh, "download") / "video.mp4"
    out.write_text("dummy", encoding="utf-8")
    assert not cache.has(vh, "download")
    cache.write_meta(vh, "download", out, extra={"title": "测试"})
    assert cache.has(vh, "download")
    got = cache.get_output(vh, "download")
    assert got is not None and got.exists()
    assert got.read_text(encoding="utf-8") == "dummy"


def test_cache_get_output_missing(tmp_path):
    cache = Cache(root=tmp_path)
    assert cache.get_output("nope", "download") is None
