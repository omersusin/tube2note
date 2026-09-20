"""Offline stand-ins for yt-dlp and the Gemini API, so the whole pipeline can run in tests (and in subprocesses).

In-process:   fake_ydl.install(monkeypatch)
Subprocess:   put a sitecustomize.py that calls fake_ydl.install() on PYTHONPATH (see tests/test_web.py)
"""
import io
import json
import re
import sys
import time
import urllib.request

import yt_dlp

VIDS = {
    "aaaaaaaaaaa": ("Alpha talk", "en", ["Hello and welcome um to the show.", "Today we talk about about testing.",
                                         "Thanks for watching. Bye bye."]),
    "bbbbbbbbbbb": ("Beta: Türkçe", "tr", ["Merhaba ee arkadaşlar.", "Bugün test yazıyoruz.", "Hoşça kalın."]),
    "ccccccccccc": ("Gamma (no subs)", None, None),
    "ddddddddddd": ("Delta long", "en", [f"This is sentence number {i} of the long video. It goes on and on."
                                        for i in range(20)]),
}
GERMAN = {"eeeeeeeeeee": ("Deutsch", "de", ["Er ist um drei Uhr zurück.", "Ah, das ist wirklich gut so.",
                                           "Wir sehen uns morgen wieder, wenn er kommt."])}

_real_urlopen = urllib.request.urlopen
CALLS = {"video_info": [], "gemini": []}


def make_vtt(lines):
    out = ["WEBVTT", ""]
    for i, text in enumerate(lines):
        out += [f"00:00:{i * 5:02d}.000 --> 00:00:{i * 5 + 4:02d}.000", text, ""]
    return "\n".join(out)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeYDL:
    catalog = VIDS

    def __init__(self, opts=None):
        self.opts = opts or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if "list=" in url or "/@" in url or "playlist" in url:
            return {"_type": "playlist", "id": "PLfake", "title": "Fake list", "entries": [
                {"id": k, "title": v[0], "channel": "FakeChan", "ie_key": "Youtube", "timestamp": 1735689600 + i}
                for i, (k, v) in enumerate(self.catalog.items())]}
        vid = url.split("v=")[-1][:11]
        CALLS["video_info"].append(vid)
        if vid not in self.catalog:
            raise RuntimeError("unknown video " + vid)
        title, lg, lines = self.catalog[vid]
        info = {"id": vid, "title": title, "channel": "FakeChan", "uploader": "FakeChan", "upload_date": "20250101",
                "duration": 60, "view_count": 42, "description": "desc " + vid, "subtitles": {},
                "automatic_captions": {},
                "chapters": [{"start_time": 0, "title": "Intro"}, {"start_time": 5, "title": "Main"}]
                if vid == "aaaaaaaaaaa" else None}
        if lines:
            info["subtitles"] = {lg: [{"ext": "vtt", "url": f"fake://{vid}"}]}
        return info

    def download(self, urls):  # audio for --transcribe
        open(self.opts["outtmpl"] % {"ext": "mp3"}, "wb").write(b"ID3fakeaudio" * 10)

    def urlopen(self, req):
        return _Resp(make_vtt(self.catalog[req.url.split("//")[-1]][2]).encode())


def fake_urlopen(req, timeout=0):
    url = getattr(req, "full_url", str(req))
    if "generativelanguage.googleapis.com" not in url:
        return _real_urlopen(req, timeout=timeout)
    parts = json.loads(req.data)["contents"][0]["parts"]
    CALLS["gemini"].append(req.get_header("X-goog-api-key"))
    if any("inline_data" in p for p in parts):
        text = "This is a transcribed sentence. It has enough words to pass the minimum length check easily."
    else:
        prompt = parts[0]["text"]
        if prompt.startswith("Translate"):
            body = prompt.split("\n\n", 1)[1]
            text = "\n".join(re.sub(r"^\[(\d+)\] ", r"[\1] TR: ", ln) for ln in body.splitlines())
        else:
            text = "SUMMARY of the video."
    return _Resp(json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode())


def install(mp=None, extra_videos=None):
    """Patch yt-dlp, urllib (Gemini only), time.sleep and GEMINI_API_KEY. mp = pytest monkeypatch, or None for a
    permanent patch (subprocess shims)."""
    def put(obj, name, value):
        mp.setattr(obj, name, value) if mp else setattr(obj, name, value)

    if extra_videos:
        put(FakeYDL, "catalog", {**VIDS, **extra_videos})

    put(yt_dlp, "YoutubeDL", FakeYDL)
    for name, mod in list(sys.modules.items()):
        if name.startswith("tube2note.") and hasattr(mod, "YoutubeDL"):
            put(mod, "YoutubeDL", FakeYDL)
    put(urllib.request, "urlopen", fake_urlopen)
    put(time, "sleep", lambda s: None)
    if mp:
        mp.setenv("GEMINI_API_KEY", "fake-key")
    else:
        import os
        os.environ["GEMINI_API_KEY"] = "fake-key"
