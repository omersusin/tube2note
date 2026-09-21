"""End-to-end pipeline tests against the offline fake yt-dlp (no network)."""
import os

LIST = "https://www.youtube.com/playlist?list=PLfake"


def read(p):
    return open(p, encoding="utf-8").read()


def test_single_layout(run, home):
    out = run("-d", str(home / "o"), "-o", "s.md", "--lang", "en,tr", LIST)
    md = read(home / "o" / "s.md")
    assert "## 1. Alpha talk" in md and "### Intro" in md
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
    monkeypatch.setattr(j, "expand", lambda urls, max_n, since=None, fresh=False: (vids, None))

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
