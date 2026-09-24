"""T3: innertube fallback, clean_cues, diarize/label/summarize fail-open, diarize/fast-subs pipeline."""
import io
import json
import urllib.request

VID = "aaaaaaaaaaa"
LIST = "https://www.youtube.com/playlist?list=PLfake"
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n"
SRV3 = '<transcript><text start="1.5">hi there</text></transcript>'


class _R(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _url(req):
    return getattr(req, "full_url", None) or getattr(req, "url", None) or str(req)


def _mock(monkeypatch, vtt_body, srv3_body, ttml_body=""):
    player = json.dumps({"captions": {"playerCaptionsTracklistRenderer": {
        "captionTracks": [{"languageCode": "en", "baseUrl": "https://x.test/get?x=1"}]}}}).encode()

    def fake(req, timeout=0):
        u = _url(req)
        if "youtubei/v1/player" in u:
            return _R(player)
        if "fmt=vtt" in u:
            if vtt_body is None:
                raise IOError("vtt dead")
            return _R(vtt_body.encode())
        if "fmt=srv3" in u:
            if srv3_body is None:
                raise IOError("srv3 dead")
            return _R(srv3_body.encode())
        if "fmt=ttml" in u:
            if not ttml_body:
                raise IOError("ttml dead")
            return _R(ttml_body.encode())
        raise AssertionError("unexpected url " + u)

    monkeypatch.setattr(urllib.request, "urlopen", fake)


def test_innertube_vtt_ok(monkeypatch):
    _mock(monkeypatch, VTT, SRV3)
    from tube2note.source import innertube_subs
    assert innertube_subs(VID, "en") == [(1.0, "hello")]


def test_innertube_srv3_fallback(monkeypatch):
    _mock(monkeypatch, "WEBVTT\n\nno cues here\n", SRV3)
    from tube2note.source import innertube_subs
    assert innertube_subs(VID, "en") == [(1.5, "hi there")]


def test_innertube_all_fail(monkeypatch):
    _mock(monkeypatch, None, None)
    from tube2note.source import innertube_subs
    assert innertube_subs(VID, "en") == []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: 1 / 0)
    assert innertube_subs(VID, "en") == []


def test_clean_cues_snap_split_merge():
    from tube2note.export_srt import clean_cues
    out = clean_cues([(0, 1.0, "a"), (1.0, 2.0, "b")])
    assert abs(out[0][1] - 0.92) < 1e-6  # snap end before next start
    out = clean_cues([(0, 10.0, ("word " * 60).strip())])
    assert len(out) > 1 and abs(out[-1][1] - 10.0) < 1e-6  # long cue split, contig
    assert clean_cues([(0, 1.0, "a"), (1.1, 2.0, "b")]) == [(0, 2.0, "a b")]  # tiny gap merged


def test_diarize_gap_flip():
    from tube2note.whisper import diarize_segs
    out = diarize_segs([(0, "a"), (1, "b"), (10, "c")])
    assert [s for _, _, s in out] == ["SPEAKER_01", "SPEAKER_01", "SPEAKER_02"]


def test_label_fail_open(monkeypatch):
    import tube2note.llm as llm
    from tube2note.whisper import label_segs_llm
    monkeypatch.setattr(llm, "_gemini_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")))
    segs = [(0.0, "hi", "SPEAKER_01")]
    assert label_segs_llm(segs) == segs


def test_summarize_first_fail_open(monkeypatch):
    import tube2note.llm as llm
    monkeypatch.setattr(llm, "_gemini_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")))
    assert llm.summarize_first("hello world") == ("", [])


def test_diarize_pipeline(run, home):
    run("-d", str(home / "o"), "-o", "d.md", "--lang", "en", "--diarize",
        "https://www.youtube.com/watch?v=aaaaaaaaaaa")
    assert "SPEAKER_01:" in (home / "o" / "d.md").read_text(encoding="utf-8")


def test_fast_subs_skips_transcribe(run, home):
    run("-d", str(home / "t"), "-o", "t.md", "--lang", "en", "--transcribe",
        "https://www.youtube.com/watch?v=ccccccccccc")
    assert "transcribed sentence" in (home / "t" / "t.md").read_text(encoding="utf-8")
    run("-d", str(home / "f"), "-o", "f.md", "--lang", "en", "--transcribe", "--fast-subs",
        "https://www.youtube.com/watch?v=ccccccccccc")
    md = (home / "f" / "f.md").read_text(encoding="utf-8")
    assert "transcribed sentence" not in md and "no subtitles" in md


def test_innertube_live_optin():
    import os

    import pytest
    if os.environ.get("YT2MD_LIVE") != "1":
        pytest.skip("live opt-in: YT2MD_LIVE=1")
    from tube2note.source import innertube_subs
    vid = os.environ.get("YT2MD_LIVE_VID", "aqz-KE-bpKQ")
    segs = innertube_subs(vid, "en")  # real network, no mock
    assert isinstance(segs, list)
    for st, tx in segs:
        assert isinstance(st, float) and isinstance(tx, str) and tx.strip()
    assert [s for s, _ in segs] == sorted(s for s, _ in segs)
