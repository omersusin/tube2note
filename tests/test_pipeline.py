"""End-to-end pipeline tests against the offline fake yt-dlp (no network)."""
import os

LIST = "https://www.youtube.com/playlist?list=PLfake"


def read(p):
    return open(p, encoding="utf-8").read()


def test_single_layout(run, home):
    out = run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", LIST)
    md = read(home / "o" / "s.md")
    assert "## 1. Alpha talk" in md and "### Intro" not in md  # chapters gated behind --chapters
    assert "Hello and welcome to the show." in md      # filler "um" removed
    assert "Today we talk about testing." in md        # repeat collapsed
    assert "Merhaba arkadaşlar." in md                 # Turkish filler "ee" removed
    from tube2note.store import Store
    st = Store(str(home / "o" / "s.md.db"))
    assert st.done_ids() == {"aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"}
    assert any("Gamma" in t and "no subtitles" in r for _, t, _, r in st.skips())
    st.close()
    assert "Done" in out


def test_resume_does_not_refetch(run, home, fake):
    args = ("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", LIST)
    run(*args)
    first = list(fake.CALLS["video_info"])
    run(*args)
    # videos in the .done log are never fetched again (the captionless one is retried on purpose)
    assert [v for v in fake.CALLS["video_info"][len(first):]] == ["ccccccccccc"]


def test_redo_replaces_one_video(run, home):
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", LIST)
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", "--redo", "aaaaaaaaaaa")
    md = read(home / "o" / "s.md")
    assert md.count("Video ID: aaaaaaaaaaa") == 1


def test_tree_and_videos_layouts(run, home):
    run("-d", str(home / "t"), "-o", "t.md", "--layout", "tree", "--timestamps", "--lang", "en,tr", LIST)
    assert (home / "t" / "INDEX.md").exists()
    tr = read(home / "t" / "FakeChan" / "Alpha talk" / "transcript.md")
    assert tr.startswith("---") and "video_id: aaaaaaaaaaa" in tr and "[00:00]" in tr
    run("-d", str(home / "v"), "-o", "v.md", "--layout", "videos", "--lang", "en,tr", LIST)
    assert (home / "v" / "videos" / "Alpha talk [aaaaaaaaaaa].md").exists()


def test_split_words(run, home):
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", "--split-words", "10", LIST)
    parts = sorted(f for f in os.listdir(home / "o") if "_part" in f)
    assert len(parts) >= 2


def test_gemini_summarize_translate_transcribe(run, home, fake):
    run("-d", str(home / "o"), "-o", "g.md", "--lang", "en,tr", "--summarize", "--translate", "de", "--transcribe", LIST)
    md = read(home / "o" / "g.md")
    assert "SUMMARY of the video." in md      # only the long video is summarized (> 100 words)
    assert "TR: " in md                       # translated paragraphs
    assert "transcribed sentence" in md       # captionless video was transcribed
    assert set(fake.CALLS["gemini"]) == {"fake-key"}


def test_german_transcript_not_mangled(run, home, fake, monkeypatch):
    """Regression: filler removal used to strip 'Er', 'um', 'Ah' from every language."""
    fake.install(monkeypatch, extra_videos=fake.GERMAN)
    run("-d", str(home / "o"), "-o", "d.md", "--lang", "de", LIST)
    md = read(home / "o" / "d.md")
    assert "Er ist um drei Uhr zurück." in md and "Ah, das ist wirklich gut so." in md


def test_status_json(run, home):
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", LIST)
    out = run("status", str(home / "o"), "--json")
    assert '"collection": "s.md"' in out and '"done": 3' in out


def test_link_timestamps_and_srt(run, home):
    out = run("-d", str(home / "o"), "-o", "l.md", "--lang", "en,tr",
              "--link-timestamps", "--srt", LIST)
    md = read(home / "o" / "l.md")
    assert "youtu.be/aaaaaaaaaaa?t=" in md  # markers became clickable links
    srt = read(home / "o" / "l_aaaaaaaaaaa.srt")
    assert "-->" in srt and ",000" in srt and "Hello and welcome" in srt
    assert "Done" in out


def test_sqlite_store_migrates_legacy(run, home):
    (home / "o").mkdir()
    (home / "o" / "m.md.done").write_text("aaaaaaaaaaa\n")
    (home / "o" / "m.md.skip").write_text(
        '{"title": "Old", "url": "https://www.youtube.com/watch?v=zzzzzzzzzzz",'
        ' "reason": "x"}\n')
    out = run("-d", str(home / "o"), "-o", "m.md", "--lang", "en,tr",
              "https://www.youtube.com/playlist?list=PLfake")
    assert "migrated legacy" in out
    from tube2note.store import Store
    st = Store(str(home / "o" / "m.md.db"))
    assert "aaaaaaaaaaa" in st.done_ids()
    assert st.skip_reasons().get("zzzzzzzzzzz") == "x"
    st.close()


def test_sqlite_resume_counts(run, home):
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr",
        "https://www.youtube.com/playlist?list=PLfake")
    out = run("status", str(home / "o"), "--json")
    assert '"done": 3' in out and '"skipped": 1' in out


def test_epub_command_and_flag(run, home):
    run("-d", str(home / "o"), "-o", "e.md", "--lang", "en,tr", "--epub",
        "https://www.youtube.com/playlist?list=PLfake")
    assert (home / "o" / "e.epub").exists()
    import zipfile
    names = zipfile.ZipFile(home / "o" / "e.epub").namelist()
    assert "mimetype" in names and any(n.endswith(".xhtml") for n in names)
    out = run("epub", str(home / "o" / "e.md"))
    assert "EPUB:" in out


def test_rss_fast_path_parses(home):
    import io

    from tube2note.source import rss_videos
    xml = ('<feed xmlns="http://www.w3.org/2005/Atom" '
           'xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
           "<title>Ch</title>"
           '<entry><yt:videoId>aaaaaaaaaaa</yt:videoId><published>2026-09-01T10:00:00+00:00</published>'
           "<title>New</title></entry>"
           '<entry><yt:videoId>bbbbbbbbbbb</yt:videoId><published>2020-01-01T10:00:00+00:00</published>'
           "<title>Old</title></entry></feed>")
    vids = rss_videos("https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx",
                      1788000000, opener=lambda req: io.BytesIO(xml.encode()))
    assert [v["id"] for v in vids] == ["aaaaaaaaaaa"]
    assert rss_videos("https://www.youtube.com/watch?v=aaaaaaaaaaa", 1788000000,
                      opener=lambda req: 1 / 0) is None  # not a channel: fall back


def test_dedupe_skips_same_transcript(home, monkeypatch):
    import tube2note.job as j
    vids = [{"id": "aaaaaaaaaaa", "title": "A", "url": "http://a"},
            {"id": "bbbbbbbbbbb", "title": "B", "url": "http://b"}]
    monkeypatch.setattr(j, "expand", lambda urls, max_n, since=None, fresh=False, **k: (vids, None))

    def fake_fetch(ydl_opts, v, langs, ts, bucket, fetch_gap, clean=True, clean_level="full",
                   *a):
        from tube2note.vtt import _join_paras, vtt_segments
        segs = vtt_segments("WEBVTT\n\n00:01.000 --> 00:02.000\nsame text here folks, this is a long shared transcript for length ok yes\n")
        return {"v": v, "title": v["title"], "wurl": v["url"], "channel": "C",
                "lg": "en", "auto": False, "text": _join_paras(segs, False, None).strip(),
                "segs": segs, "error": None, "throttled": False, "stage": "ok",
                "chapters": [], "meta": {}}
    monkeypatch.setattr(j, "_fetch_unit", fake_fetch)
    res = j.run_job(["http://x"], "d.md", "en", 10, 0, outdir=str(home / "o"), verbose=False)
    assert res == {"ok": 1, "skipped": 1, "total": 2}
    md = (home / "o" / "d.md").read_text(encoding="utf-8")
    assert md.count("Video ID: ") == 1 and "duplicate transcript" in md


def test_obsidian_frontmatter(run, home):
    run("-d", str(home / "o"), "-o", "b.md", "--layout", "videos", "--lang", "en,tr",
        "--obsidian", "https://www.youtube.com/playlist?list=PLfake")
    md = read(home / "o" / "videos" / "Alpha talk [aaaaaaaaaaa].md")
    assert "tags: [youtube, transcript, youtube/channel/" in md and "aliases:" in md


def test_cookies_from_browser_reaches_ydl(home, monkeypatch, fake):
    import tube2note.job as j
    seen = {}
    real_ydl = j.YoutubeDL

    class SpyYDL(real_ydl):
        def __init__(self, *a, **k):
            seen.update(k.get("params", a[0] if a else {}))
            super().__init__(*a, **k)
    monkeypatch.setattr(j, "YoutubeDL", SpyYDL)
    import sys

    from tube2note.cli import main
    monkeypatch.setattr(sys, "argv", ["tube2note", "--fetch-gap", "0", "--sleep", "0",
                                      "--cookies-from-browser", "chrome",
                                      "-d", str(home / "o"), "-o", "c.md",
                                      "https://www.youtube.com/playlist?list=PLfake"])
    main()
    assert seen.get("cookiesfrombrowser") == "chrome"


def test_jsonl_rows_resume_redo(run, home):
    import json
    args = ("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", "--jsonl",
            "https://www.youtube.com/playlist?list=PLfake")

    def rows():
        return [json.loads(l) for l in open(home / "o" / "s.md.jsonl", encoding="utf-8")]
    run(*args)
    assert {r["video_id"] for r in rows()} == {"aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"}
    r0 = rows()[0]
    assert set(r0) == {"video_id", "title", "url", "channel", "lang", "text", "words"}
    assert r0["words"] == len(r0["text"].split())
    n = len(rows())
    run(*args)  # resume: no new rows
    assert len(rows()) == n
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", "--jsonl",
        "--redo", "aaaaaaaaaaa", "https://www.youtube.com/watch?v=aaaaaaaaaaa")
    vids = [r["video_id"] for r in rows()]
    assert vids.count("aaaaaaaaaaa") == 1


def test_stdout_clean_pipe(home, monkeypatch, capsys, fake):
    import sys

    from tube2note.cli import main
    monkeypatch.setattr(sys, "argv", ["tube2note", "--fetch-gap", "0", "--sleep", "0",
                                      "-o", "-", "--lang", "en,tr",
                                      "https://www.youtube.com/playlist?list=PLfake"])
    main()
    r = capsys.readouterr()
    assert "## 1. Alpha talk" in r.out and "Hello and welcome to the show." in r.out
    assert "Done" not in r.out and "videos found" not in r.out and "videos ·" not in r.out
    odir = home / "o"
    assert (not odir.exists()) or list(odir.iterdir()) == []  # NO files written


def test_stdout_rejects_sidecars(home, monkeypatch, capsys, fake):
    import sys

    import pytest

    from tube2note.cli import main
    for extra in (["--pdf"], ["--epub"], ["--srt"], ["--split-words", "10"],
                  ["--layout", "videos"], ["--jsonl"]):
        monkeypatch.setattr(sys, "argv", ["tube2note", "-o", "-", *extra,
                                          "https://www.youtube.com/playlist?list=PLfake"])
        with pytest.raises(SystemExit):
            main()
        capsys.readouterr()


def test_bilingual_interleaved(run, home, fake):
    run("-d", str(home / "o"), "-o", "b.md", "--lang", "en,tr", "--bilingual", "de", LIST)
    md = read(home / "o" / "b.md")
    assert "### Bilingual (de)" in md and "> TR: " in md
    assert "### Translation" not in md  # interleaved, not sections


def test_bilingual_mismatch_falls_back(run, home, fake, monkeypatch):
    import tube2note.job as J
    monkeypatch.setattr(J, "_translate_chunks", lambda t, tg, m: "single merged para")
    run("-d", str(home / "o"), "-o", "b2.md", "--lang", "en,tr", "--bilingual", "de", LIST)
    assert "### Translation (de)" in read(home / "o" / "b2.md")


def test_zip_bilingual_unit():
    from tube2note.llm import _zip_bilingual
    ok, b = _zip_bilingual("a\nb", "A\nB")
    assert ok and "> A" in b
    assert _zip_bilingual("a\nb", "A")[0] is False
    assert _zip_bilingual("", "")[0] is False
    ok, b = _zip_bilingual("### Intro\nhello", "### Giris\nmerhaba")
    assert ok and "> ###" not in b


def test_sponsorblock_pipeline_mocked(run, home, fake, monkeypatch):
    import tube2note.source as src
    monkeypatch.setattr(src, "sponsor_ranges",
                        lambda vid, cats=("sponsor",): [(0, 5)] if vid == "aaaaaaaaaaa" else [])
    run("-d", str(home / "o"), "-o", "s.md", "--lang", "en", "--sponsorblock", LIST)
    md = read(home / "o" / "s.md")
    assert "Hello and welcome" not in md  # mocked range stripped
    assert "Today we talk about testing." in md and "Thanks for watching" in md
    run("-d", str(home / "p"), "-o", "s.md", "--lang", "en", LIST)
    assert "Hello and welcome" in read(home / "p" / "s.md")


def test_cite_pipeline_bib_ris_content(run, home):
    run("-d", str(home / "o"), "-o", "c.md", "--lang", "en,tr", "--cite", LIST)
    bib_p, ris_p = home / "o" / "c.bib", home / "o" / "c.ris"
    assert bib_p.exists() and ris_p.exists()
    bib, ris = read(bib_p), read(ris_p)
    assert "Alpha talk" in bib and "aaaaaaaaaaa" in bib and bib.count("@misc{") >= 3
    assert "Alpha talk" in ris and "TY  - ELEC" in ris and "aaaaaaaaaaa" in read(home / "o" / "c.md")
