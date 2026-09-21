"""Round-2 gap tests: untested paths found by adversarial audit (all offline)."""
import collections
import io
import json
import os
import threading

import pytest


def test_finally_closes_on_systemexit(home, monkeypatch):
    import tube2note.job as j
    tmp = str(home / "tmp")
    os.makedirs(tmp)
    monkeypatch.setattr(j.tempfile, "mkdtemp", lambda prefix="": tmp)
    blob = {"stage": "ok", "title": "A", "wurl": "u", "lg": "en", "auto": False,
            "text": "x " * 30, "segs": []}

    def boom(*a, **k):
        yield 1, {"id": "aaaaaaaaaaa", "title": "A", "url": "u"}, dict(blob)
        raise SystemExit(1)
    monkeypatch.setattr(j, "_stream", boom)
    monkeypatch.setattr(j, "expand", lambda urls, max_n, since=None, fresh=False, **k:
                        ([{"id": "aaaaaaaaaaa", "title": "A", "url": "u"}], None))
    with pytest.raises(SystemExit):
        j.run_job(["u"], "s.md", "en", 10, 0, outdir=str(home / "o"))
    assert os.path.exists(home / "o" / "s.md.db")  # resume store written before the raise
    from tube2note.store import Store
    st = Store(str(home / "o" / "s.md.db"))
    assert "aaaaaaaaaaa" in st.done_ids()
    st.close()
    assert not os.path.exists(tmp)  # temp audio cleaned by finally


def test_stop_cancels_first_timer(monkeypatch):
    import tube2note.web as w
    timers = []

    class T:
        def __init__(self, s, fn):
            self.fn = fn
            self.cancelled = False
        def start(self):
            timers.append(self)
        def cancel(self):
            self.cancelled = True
    monkeypatch.setattr(w.threading, "Timer", T)
    monkeypatch.setattr(w.os, "name", "posix")
    job = w.Job.__new__(w.Job)
    job._timer = None
    job.stopped = False

    class P:
        def send_signal(self, sig):
            pass
        def poll(self):
            return None
    job.proc = P()
    job.stop()
    job.stop()
    assert len(timers) == 2 and timers[0].cancelled and not timers[1].cancelled


def test_pump_closes_stdout_on_error():
    import tube2note.web as w
    job = w.Job.__new__(w.Job)
    job.lock = threading.Lock()
    job.lines = collections.deque(maxlen=400)
    job.progress = {}
    job.current = ""
    closed = []

    class BadOut:
        def __iter__(self):
            yield "1/2 videos · 5 words"
            raise RuntimeError("boom")
        def close(self):
            closed.append(True)
    job.proc = type("P", (), {"stdout": BadOut(), "wait": lambda self: 0})()
    job.ended = None
    job._timer = None
    with pytest.raises(RuntimeError):
        job._pump()
    assert closed and job.ended is not None


def test_interval_loop_sleeps_minutes(home, monkeypatch, capsys):
    import tube2note.watch as w
    sleeps = []

    def nap(s):
        sleeps.append(s)
        raise KeyboardInterrupt
    monkeypatch.setattr(w.time, "sleep", nap)
    monkeypatch.setattr(w, "_check", lambda *a, **k: 0)
    assert w.cmd_watch(["http://ch", "-o", "w.md", "--interval", "5"]) == 0
    assert sleeps == [300.0]
    assert "next check in 5 min" in capsys.readouterr().out


def test_watch_link_srt_plumbing(home, monkeypatch):
    import tube2note.watch as w2
    calls = []
    monkeypatch.setattr(w2, "expand", lambda urls, max_n, **k: ([{"id": "v1", "title": "T",
                                                                "url": "http://v1"}], None))
    monkeypatch.setattr(w2, "run_job",
                        lambda urls, *a, **k: calls.append(k) or {"ok": 1, "skipped": 0, "total": 1})
    w2.cmd_watch(["http://ch", "-o", "w.md", "--sleep", "0", "--timestamps",
                  "--link-timestamps", "--srt"])
    assert calls and calls[0]["link_timestamps"] is True and calls[0]["srt"] is True


def test_resume_last_roundtrips_link_srt(run, home):
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr",
        "--link-timestamps", "--srt", "https://www.youtube.com/playlist?list=PLfake")
    import tube2note.config as cfg
    last = cfg.load_config()["last"]
    assert last["link_timestamps"] is True and last["srt"] is True
    assert (home / "o" / "s_aaaaaaaaaaa.srt").exists()


def test_mcp_download_systemexit_is_error(monkeypatch):
    import tube2note.job as job
    from tube2note.mcp import _handle
    monkeypatch.setattr(job, "run_job", lambda *a, **k: (_ for _ in ()).throw(SystemExit(1)))
    r, _ = _handle({"id": 1, "method": "tools/call",
                    "params": {"name": "download", "arguments": {"url": "http://v"}}})
    assert r["result"]["isError"] and "error:" in r["result"]["content"][0]["text"]


def test_get_vtt_unlinks_poison(home, monkeypatch):
    from tube2note import source as s
    monkeypatch.setattr(s.time, "sleep", lambda *a: None)
    p = s._cache_path("vid1", "en", False)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("error page, no cue")
    vtt, cached = s._get_vtt("vid1", "en", False, [{"url": "http://a", "ext": "vtt"}],
                             lambda req: io.BytesIO(b"WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n"))
    assert (vtt, cached) == ("WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n", False)
    assert "-->" in open(p).read()
    vtt2, c2 = s._get_vtt("vid2", "en", False, [{"url": "http://b", "ext": "vtt"}],
                          lambda req: io.BytesIO(b"nope"))
    assert c2 is False and not os.path.exists(s._cache_path("vid2", "en", False))


def test_search_limit(home, capsys):
    from tube2note.search import search_collections
    for i in range(3):
        (home / f"f{i}.md").write_text("\n".join(f"## {j}. T\n\nhit line {j}\n" for j in range(10)),
                                       encoding="utf-8")
    assert search_collections("hit line", str(home), limit=5) == 0
    assert capsys.readouterr().out.count("- [") <= 5
    capsys.readouterr()
    assert search_collections("hit line", str(home), as_json=True, limit=5) == 0
    assert len(json.loads(capsys.readouterr().out)) <= 5


@pytest.mark.parametrize("text,expected", [
    ("Привет. Как дела? Хорошо!", "Привет.\nКак дела?\nХорошо!"),
    ("Γεια. Τι κάνεις! Καλά.", "Γεια.\nΤι κάνεις!\nΚαλά."),
    ("Hello e.g. Smith. Next.", "Hello e.g. Smith.\nNext."),
    ("Value is 3.14 ok. Next.", "Value is 3.14 ok.\nNext."),
    ("Met Dr. No. He left.", "Met Dr. No.\nHe left."),
])
def test_clean_unicode_and_abbr(text, expected):
    from tube2note.clean import _clean_text
    assert _clean_text(text, "en") == expected


def test_tui_link_srt_plumbing(home, monkeypatch):
    import tube2note.tui as t
    monkeypatch.setattr(t, "is_first_run", lambda: False)
    monkeypatch.setattr(t, "expand", lambda urls, max_n, since=None: (
        [{"id": "aaaaaaaaaaa", "title": "A", "url": urls[0]}], "H"))
    monkeypatch.setattr(t, "detect_langs", lambda videos: ("en", []))
    answers = iter(["https://www.youtube.com/watch?v=aaaaaaaaaaa", "", "", "", "", "",
                    "", "", "n", "y", "y", "y", "n", "y", "tr", "", "n", "n", "", "", "", "", "q"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    got = {}
    monkeypatch.setattr(t, "run_job", lambda *a, **k: got.update(k) or {"ok": 1, "skipped": 0, "total": 1})
    t.tui()
    assert got["link_timestamps"] is True and got["srt"] is True
    assert got["transcribe"] is True and got["engine"] == "api"
    assert got["summarize"] is True and got["translate"] == "tr"
    assert got["epub"] is False


def test_web_bool_flags_and_checkboxes():
    from tube2note.web import INDEX_HTML, build_argv
    argv = build_argv({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
                       "link_timestamps": True, "srt": "1"}, "/d")
    assert "--link-timestamps" in argv and "--srt" in argv
    assert 'id="link_timestamps"' in INDEX_HTML and 'id="srt"' in INDEX_HTML
    assert '"link_timestamps"' in INDEX_HTML and '"srt"' in INDEX_HTML  # JS BOOLS persistence
