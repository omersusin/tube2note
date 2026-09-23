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
    from tube2note.store import Store
    st = Store(str(home / "w" / "w.md.db"))
    assert st.done_ids() == {"aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"}
    st.close()


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


def test_vtt_named_cue_ids_and_notes():
    from tube2note.vtt import vtt_segments
    vtt = ("WEBVTT\n\nNOTE this is a note\ncontinued note\n\n"
           "cue-99\n00:01.000 --> 00:02.000\nhello\n\n"
           "00:03.000 --> 00:04.000\na --> b\n")
    segs = vtt_segments(vtt)
    assert segs == [(1.0, "hello")]  # NOTE block + named id skipped; prose "-->" is a cue boundary per VTT spec
    assert vtt_segments("WEBVTT\n\n00:01.000 --> 00:02.000\n3 < 5 > 2\n") == [(1.0, "3 < 5 > 2")]
    assert vtt_segments("WEBVTT\n\n-00:00:01.000 --> 00:02.000\nx\n")[0][0] == 0.0


def test_clean_filler_debris_and_abbr():
    from tube2note.clean import _clean_text
    assert _clean_text("um. Hello world test here", "en") == "Hello world test here"
    assert _clean_text("Use e.g. this case here now", "en") == "Use e.g. this case here now"
    assert _clean_text("Meet at 5 p.m. we go home now", "en") == "Meet at 5 p.m. we go home now"


def test_links_idempotent_and_validated():
    from tube2note.links import linkify
    once = linkify("[00:01] hi there friend", "VID1")
    assert once == "[00:01](https://youtu.be/VID1?t=1s) hi there friend"
    assert linkify(once, "VID1") == once
    assert linkify("[99:99] hi there friend now", "VID1") == "[99:99] hi there friend now"


def test_srt_negative_and_unsorted():
    from tube2note.export_srt import fmt_srt_ts, segs_to_srt
    assert fmt_srt_ts(-1.5) == "00:00:00,000"
    out = segs_to_srt([(5.0, 6.0, "b"), (1.0, 2.0, "a")])
    assert out.startswith("1\n") and "\n2\n" in out and "00:00:01,000 --> 00:00:02,000" in out


def test_naming_reserved_with_extension():
    from tube2note.naming import sanitize_filename, slug
    assert sanitize_filename("con.txt").startswith("_")
    assert slug("con") == "_con.md"


def test_throttle_context_and_private():
    from tube2note.throttle import _is_throttle
    assert not _is_throttle(Exception("view count 429 today"))
    assert _is_throttle(Exception("ERROR: HTTP Error 429"))
    assert not _is_throttle(Exception("Video unavailable. This video is private. Error 403"))
    assert _is_throttle(Exception("ERROR: HTTP Error 403: Forbidden"))
    assert _is_throttle(Exception("HTTP Error 503: Service Unavailable"))


def test_retry_after_float():
    from tube2note.throttle import _retry_after_hint

    class E(Exception):
        def __init__(self, headers=None):
            super().__init__("err")
            self.headers = headers
    assert _retry_after_hint(E({"Retry-After": "120.5"}), 60) == 120
    assert _retry_after_hint(E({"Retry-After": "120s"}), 60) == 120


def test_source_none_guards():
    from tube2note.source import _flatten, fetch_vtt
    out = []
    _flatten(None, {"id": None, "_type": "x"}, out, 10)
    assert out == []
    try:
        fetch_vtt(None)
        raise AssertionError("should raise")
    except RuntimeError:
        pass
    try:
        fetch_vtt([{"url": None, "ext": "vtt"}])
        raise AssertionError("should raise")
    except RuntimeError:
        pass


def test_store_corrupt_recovers(tmp_path):
    from tube2note.store import Store
    p = str(tmp_path / "c.db")
    open(p, "w").write("garbage not sqlite")
    st = Store(p)
    st.mark_done("V1", "T", "u", 5)
    assert st.done_ids() == {"V1"}
    st.close()
