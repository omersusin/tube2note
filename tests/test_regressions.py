"""Regressions found in the 0.2.1 review: each of these used to silently lose or corrupt data."""
from tube2note import web
from tube2note.vtt import vtt_segments, vtt_to_text

LIST = "https://www.youtube.com/playlist?list=PLfake"

VTT = """WEBVTT
Kind: captions
Language: en

1
00:00:00.000 --> 00:00:03.000 align:start position:0%
We're about to enter

00:00:03.000 --> 00:00:05.000
the year
1999

00:00:05.000 --> 00:00:07.000
and it&nbsp;started.
"""


def test_vtt_header_metadata_does_not_leak():
    text = vtt_to_text(VTT)
    assert "Kind:" not in text and "Language:" not in text
    assert text.startswith("We're about to enter")


def test_spoken_number_on_its_own_line_is_kept():
    assert "1999" in vtt_to_text(VTT)


def test_numeric_cue_identifier_is_dropped():
    assert all(t != "1" for _, t in vtt_segments(VTT))


def test_nbsp_becomes_space():
    assert "it started." in vtt_to_text(VTT)


def test_non_vtt_input_is_not_swallowed():
    assert vtt_segments("just some text") == []  # corrupt cache must refetch, never poison output


def test_parallel_workers_write_every_video(run, home):
    """--workers 2 used to fetch everything and write nothing (result loop sat outside the while)."""
    run("-d", str(home / "w"), "-o", "w.md", "--lang", "en,tr", "--workers", "2", LIST)
    md = (home / "w" / "w.md").read_text(encoding="utf-8")
    assert "## 1. Alpha talk" in md
    assert (home / "w" / "w.md.done").read_text().split() == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"]


def test_public_mode_never_passes_gemini_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "host-secret")
    seen = {}

    def builder(payload, base_dir):
        seen.update(payload)
        return ["true"]

    app = web.App(str(tmp_path), "t", "0.0.0.0", 0, argv_builder=builder, public=True)
    app.start({"urls": ["https://youtu.be/aaaaaaaaaaa"], "summarize": True, "transcribe": True,
               "translate": "tr", "name": "x"})
    assert not {"summarize", "transcribe", "translate"} & set(seen) and seen["name"] == "x"
    assert app.state()["gemini"] is False


def test_local_mode_still_offers_gemini(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert web.App(str(tmp_path), "t", "127.0.0.1", 0).state()["gemini"] is True
