from tube2note.export_srt import fmt_srt_ts, segs_to_srt
from tube2note.links import fmt_label, link_ts, para_text
from tube2note.subs import load_subs


def test_labels():
    assert fmt_label(65) == "01:05" and fmt_label(3665).startswith("1:")
    assert link_ts("01:05", "dQw4w9WgXcQ", 65) == "[01:05](https://youtu.be/dQw4w9WgXcQ?t=65s)"
    assert para_text(65, "hi", None, False) == "[01:05] hi"

def test_srt():
    assert fmt_srt_ts(5) == "00:00:05,000"
    s = segs_to_srt([(5.0, 9.0, "hi"), (9.0, 12.0, "yo")])
    assert s.splitlines()[0] == "1" and "-->" in s and s.count("-->") == 2

def test_subs(tmp_path):
    p = tmp_path / "subs.yaml"
    p.write_text("# c\n- url: https://www.youtube.com/@Ch/videos\n  out: ch.md\n", encoding="utf-8")
    assert load_subs(str(p))[0]["out"] == "ch.md"
    assert load_subs(str(tmp_path / "missing.yaml")) == []

def test_pwa_files():
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(root, "docs", "app.js"), encoding="utf-8").read()
    assert "X-Token" in js and "/api/start" in js and "/api/download?path=" in js
    assert "&t=" in js  # ?t= fallback for <a> navigation
    html = open(os.path.join(root, "docs", "app.html"), encoding="utf-8").read()
    ids = set(re.findall(r'id="([^"]+)"', html))
    # every app.js payload key must be accepted by backend build_argv (split->split_words alias)
    from tube2note.web import build_argv
    payload_keys = set(re.findall(r'(\w+): \$', js)) | {"urls", "name", "lang", "layout", "max",
        "since", "timestamps", "clean", "link_timestamps", "srt", "vtt", "anki",
        "chapters", "sponsorblock", "cite", "obsidian", "transcribe", "summarize",
        "translate", "bilingual", "pdf", "epub", "cookies", "cookies_from_browser",
        "split_words", "workers"}
    base = {"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"], "name": "x.md"}
    for k in payload_keys:
        if k in ("urls", "split"):
            continue
        probe = dict(base)
        probe[k] = _val(k)
        build_argv(probe, "/tmp/x")  # must not raise "bad request" for known keys
    for k in payload_keys:
        assert k in ids or k == "split_words", k
    assert "split" in ids  # frontend id for split_words


def _val(k):
    return {"translate": "tr", "bilingual": "de", "max": 5, "split_words": 0,
            "workers": 1, "since": "2024-01-01", "lang": "en", "layout": "single",
            "name": "x.md", "cookies": "/tmp/c.txt",
            "cookies_from_browser": "chrome"}.get(k, True)

def test_server_api_shape():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "tube2note", "server_api.py"), encoding="utf-8").read()
    assert '@app.get("/healthz")' in src and '@app.post("/api/start")' in src
    assert '@app.get("/api/download")' in src and "x_token" in src
    assert "youtube.com" in src and "youtu.be" in src  # allow-list, not regex
    assert "MAX_JOBS" in src and "MAX_JOBS_ENTRIES" in src
    assert "_is_trusted_proxy" in src and "TRUSTED_PROXIES" in src  # proxy-header guard
