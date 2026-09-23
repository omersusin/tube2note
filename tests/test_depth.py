"""Depth coverage: cite, vtt, anki, chapters, sponsor, watch atomic, search typed (offline)."""
LIST = "https://www.youtube.com/playlist?list=PLfake"


def test_cite_formats():
    from tube2note.cite import cite_data, fmt_apa, fmt_chicago, fmt_mla, to_bibtex, to_ris
    d = cite_data({"title": "T", "channel": "C", "published": "2025-01-01",
                   "url": "https://youtu.be/aaa", "video_id": "aaa", "duration": 60})
    assert "C. (2025)." in fmt_apa(d) and "[Video]" in fmt_apa(d)
    assert "uploaded by C" in fmt_mla(d) and fmt_mla(d).endswith(".")
    assert "YouTube video" in fmt_chicago(d)
    assert to_bibtex(d).startswith("@misc{") and "author" in to_bibtex(d)
    assert "TY  - ELEC" in to_ris(d) and "ER  - " in to_ris(d)


def test_cite_bib_ris_written(run, home):
    run("-d", str(home / "o"), "-o", "c.md", "--lang", "en,tr", "--cite", LIST)
    bib = (home / "o" / "c.bib").read_text(encoding="utf-8")
    ris = (home / "o" / "c.ris").read_text(encoding="utf-8")
    md = (home / "o" / "c.md").read_text(encoding="utf-8")
    assert "@misc{" in bib and "## Citation" in md and "APA:" in md
    assert "TY  - ELEC" in ris


def test_segs_to_vtt():
    from tube2note.export_srt import segs_to_vtt
    out = segs_to_vtt([(0, 2.0, "hi"), (5, 7.0, "yo")])
    assert out.startswith("WEBVTT") and "-->" in out and ".000" in out
    assert "hi" in out and "yo" in out


def test_summary_cards():
    from tube2note.export_anki import cards_to_csv, summary_to_cards
    cards = summary_to_cards("- Paris - France\n- 2+2: 4\nplain line\n")
    assert cards[0] == ("Paris", "France") and len(cards) == 2
    csv = cards_to_csv(cards)
    assert csv.splitlines()[0] == "Front,Back,Tag" and "Paris" in csv


def test_chapters_linked(run, home):
    from tube2note.vtt import _join_paras
    got = _join_paras([(0, "a"), (6, "b")], False, [(0, "Intro"), (5, "Main")],
                      vid="aaaaaaaaaaa", link_chapters=True)
    assert "?t=0s" in got and "?t=5s" in got and "Intro" in got
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", LIST)
    assert "?t=" not in (home / "o" / "s.md").read_text(encoding="utf-8")
    run("-d", str(home / "p"), "-o", "s.md", "--lang", "en,tr", "--chapters", LIST)
    assert "?t=" in (home / "p" / "s.md").read_text(encoding="utf-8")


def test_sponsor_strip():
    from tube2note.source import strip_sponsored
    segs = [(0, "a"), (5, "b"), (10, "c")]
    assert strip_sponsored(segs, [(4, 6)]) == [(0, "a"), (10, "c")]
    assert strip_sponsored(segs, []) == segs


def test_watch_atomic(home):
    from tube2note import watch
    p = watch._state_path(["http://x"], "w.md")
    watch._save_seen(p, {"a", "b"})
    import os
    assert not os.path.exists(p + ".tmp")  # atomic: no half-written file left
    assert watch._load_seen(p) == {"a", "b"}


def test_search_typed(home, capsys):
    from tube2note.search import search_collections
    (home / "a.md").write_text('## 1. Alpha talk\nchannel: FakeChan\nVideo ID: aaa\n\nhello world foo\n', encoding="utf-8")
    (home / "b.md").write_text('## 1. Beta talk\nchannel: Other\nVideo ID: bbb\n\nhello other bar\n', encoding="utf-8")
    search_collections("title:alpha", str(home))
    out = capsys.readouterr().out
    assert "Alpha" in out and "Beta" not in out
    search_collections("hello -other", str(home))
    out = capsys.readouterr().out
    assert "a.md" in out and "b.md" not in out
    search_collections('"hello world"', str(home))
    assert "a.md" in capsys.readouterr().out
    search_collections("channel:fakechan", str(home))
    assert "a.md" in capsys.readouterr().out
    search_collections("id:bbb", str(home))
    assert "b.md" in capsys.readouterr().out
