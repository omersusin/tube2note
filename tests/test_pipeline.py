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
    skip = read(home / "o" / "s.md.skip")
    assert "Gamma" in skip and "no subtitles" in skip  # captionless video is logged, not fatal
    assert read(home / "o" / "s.md.done").split() == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"]
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
