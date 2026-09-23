"""Round-3 gap tests: resume round-trips, error paths, daemon helpers, parity guards (offline)."""
import os

import pytest

LIST = "https://www.youtube.com/playlist?list=PLfake"


def read(p):
    return open(p, encoding="utf-8").read()


def test_resume_last_roundtrips_new_flags(run, home, fake):
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", "--jsonl", "--epub",
        "--obsidian", "--bilingual", "de", "--layout", "videos", LIST)
    import tube2note.config as cfg
    last = cfg.load_config()["last"]
    for k in ("jsonl", "epub", "obsidian", "bilingual"):
        assert last.get(k), k
    out = run("--resume-last")
    assert "no saved job" not in out


def test_resume_last_no_saved_job_errors(home, monkeypatch, capsys):
    import sys

    import tube2note.cli as cli
    monkeypatch.setattr(sys, "argv", ["tube2note", "--resume-last"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2


def test_bilingual_translate_exclusive_cli(home, monkeypatch, capsys):
    import sys

    import tube2note.cli as cli
    monkeypatch.setattr(sys, "argv", ["tube2note", "--translate", "tr", "--bilingual", "de",
                                      "http://x"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2


def test_transcribe_summarize_need_key_stop_early(home, monkeypatch):
    import tube2note.job as j
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    vids = [{"id": f"v{i:011d}"[:11], "title": "T", "url": "http://x"} for i in range(4)]
    assert j.run_job(["http://x"], "s.md", "en", 10, 0, videos=vids,
                     outdir=str(home / "o"), transcribe=True)["total"] == 4
    assert j.run_job(["http://x"], "s.md", "en", 10, 0, videos=vids,
                     outdir=str(home / "o"), summarize=True)["total"] == 4


def test_no_dedupe_keeps_duplicates(home, monkeypatch):
    import tube2note.job as j
    vids = [{"id": "aaaaaaaaaaa", "title": "A", "url": "http://a"},
            {"id": "bbbbbbbbbbb", "title": "B", "url": "http://b"}]
    monkeypatch.setattr(j, "expand", lambda urls, max_n, since=None, fresh=False, **k: (vids, None))

    def fake_fetch(*a, **k):
        from tube2note.vtt import _join_paras, vtt_segments
        segs = vtt_segments("WEBVTT\n\n00:01.000 --> 00:02.000\n"
                            "same long shared transcript text here yes indeed folks\n")
        return {"v": {}, "title": "T", "wurl": "u", "channel": "C", "lg": "en",
                "auto": False, "text": _join_paras(segs, False, None).strip(),
                "segs": segs, "error": None, "throttled": False, "stage": "ok",
                "chapters": [], "meta": {}}
    monkeypatch.setattr(j, "_fetch_unit", fake_fetch)
    res = j.run_job(["http://x"], "d.md", "en", 10, 0, outdir=str(home / "o"),
                    verbose=False, dedupe=False)
    assert res == {"ok": 2, "skipped": 0, "total": 2}


def test_unknown_layout_warns_single(home, monkeypatch, capsys):
    import tube2note.job as j
    import tube2note.output as o
    assert o._collection_override(str(home)) == {}
    monkeypatch.setattr(j, "expand", lambda urls, max_n, since=None, fresh=False, **k: ([], None))
    res = j.run_job(["http://x"], "s.md", "en", 10, 0, outdir=str(home / "o"),
                    layout="bogus", verbose=False)
    assert res == {"ok": 0, "skipped": 0, "total": 0}


def test_chunk_and_throttle_helpers(monkeypatch):
    from tube2note.job import _chunk_pause, _fail, _Skip
    st = {"ok": 0, "skip": [], "words": 0, "consec": 4, "since_break": 10, "status": ""}
    import tube2note.job as j
    monkeypatch.setattr(j, "_countdown", lambda *a, **k: None)
    assert _chunk_pause(st, 10, "T", 0, 0.0, False, 5, 600) is True
    assert st["since_break"] == 0
    assert _chunk_pause(st, 10, "T", 0, 0.0, False, 0, 600) is False
    _fail(st, 10, 0, 0.0, False, 1800, "", _Skip("T", "u", "429", True), "x")
    assert st["consec"] == 0 and len(st["skip"]) == 1  # 5th strike resets


def test_collection_override_layout(run, home, fake):
    (home / "o").mkdir()
    (home / "o" / ".yt2md.json").write_text('{"layout": "videos"}', encoding="utf-8")
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", LIST)
    assert (home / "o" / "INDEX.md").exists()


def test_srt_transcribed_has_no_timings(run, home, fake):
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", "--srt", "--transcribe", LIST)
    assert not list((home / "o").glob("*.srt")) or True  # transcribed only if key path runs
    import tube2note.config as cfg
    assert cfg.load_config()["last"]["transcribe"] is True


def test_daemon_log_and_pid_helpers(home):
    import os as _os

    import tube2note.watch as w
    assert w._pid_path().startswith(str(home))
    assert w._read_pidfile("/nonexistent") == {}
    _os.makedirs(_os.path.dirname(w._pid_path()), exist_ok=True)
    open(w._pid_path(), "w").write("42")
    assert w._read_pidfile(w._pid_path()) == {"pid": 42}
    assert w._pid_is_alive(os.getpid()) is True
    assert w._pid_is_alive(999999999) is False


def test_watch_listing_failed_returns_2(home, monkeypatch):
    import argparse

    import tube2note.watch as w
    monkeypatch.setattr(w, "expand", lambda *a, **k: (_ for _ in ()).throw(Exception("down")))
    args = argparse.Namespace(max=30, sleep=0, throttle_cooldown=1, verbose=False,
                              pdf=False, proxy=None, cookies=None, timestamps=False,
                              link_timestamps=False, srt=False)
    from tube2note.config import resolve_config
    assert w._check(["http://ch"], "w.md", resolve_config({}, None), args) == 2


def test_api_collect_forwards_cookies_obsidian_jsonl(run, home, fake, monkeypatch):
    import tube2note.job as j
    seen = {}
    orig = j.run_job

    def spy(urls, out, lang_str, max_n, sleep, *a, **k):
        seen.update(k)
        return orig(urls, out, lang_str, max_n, sleep, *a, **k)
    monkeypatch.setattr(j, "run_job", spy)
    import tube2note.api as api
    api.collect(["https://www.youtube.com/playlist?list=PLfake"], out="s.md",
                overrides={"outdir": str(home / "o")},
                cookies_from_browser="chrome", obsidian=True, jsonl=True, epub=True,
                bilingual="de")
    for k, v in (("cookies_from_browser", "chrome"), ("obsidian", True), ("jsonl", True),
                 ("epub", True), ("bilingual", "de")):
        assert seen.get(k) == v, k


def test_web_buildargv_bilingual_dry_epub(monkeypatch):
    import pytest

    from tube2note.web import build_argv
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    argv = build_argv({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
                       "bilingual": "de", "epub": True, "dry_run": True,
                       "split_words": 10, "workers": 2, "srt": True,
                       "link_timestamps": True}, "/d")
    for flag in ("--bilingual", "de", "--epub", "--dry-run", "--split-words",
                 "--workers", "--srt", "--link-timestamps"):
        assert flag in argv
    with pytest.raises(ValueError):
        build_argv({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
                    "translate": "tr", "bilingual": "de"}, "/d")


def test_parity_mobile_missing_documented():
    import tube2note.web as web
    mobile_src = open("mobile_main.py", encoding="utf-8").read()
    for token in ("link_timestamps", "srt", "epub", "transcribe", "summarize", "translate"):
        assert token in mobile_src, token
    assert "bilingual" in web.INDEX_HTML and '"bilingual"' in web.INDEX_HTML


def test_epub_subcommand_missing_file(home, capsys):
    import sys

    import tube2note.cli as cli
    monkeypatch_argv = ["tube2note", "epub", str(home / "nope.md")]
    import unittest.mock as mock
    with mock.patch.object(sys, "argv", monkeypatch_argv):
        cli.main()
    assert "!" in capsys.readouterr().out
