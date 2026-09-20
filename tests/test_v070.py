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
    assert os.path.exists("docs/app.js") and os.path.exists("docs/sw.js")
    assert "X-Token" in open("docs/app.js").read()
    assert "/api/" in open("docs/sw.js").read()

def test_server_api_shape():
    import importlib.util
    assert importlib.util.find_spec("tube2note.server_api") is not None
