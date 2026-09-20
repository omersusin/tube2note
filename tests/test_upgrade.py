import io

from tube2note.config import DEFAULTS, _merge
from tube2note.source import fetch_vtt
from tube2note.throttle import _is_throttle


def test_fetch_vtt_falls_through():
    calls = []
    def opener(req):
        n = len(calls); calls.append(1)
        if n == 0:
            raise RuntimeError("mirror dead")
        return io.BytesIO(b"WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n")
    fmts = [{"url": "http://a", "ext": "vtt"}, {"url": "http://b", "ext": "vtt"}]
    assert "hi" in fetch_vtt(fmts, opener)

def test_throttle_bot_text():
    assert _is_throttle(Exception("Sign in to confirm you're not a bot"))
    assert _is_throttle(Exception("ERROR: HTTP Error 403: Forbidden"))
    assert not _is_throttle(Exception("video abc429XYZ12 unavailable"))

def test_unknown_profile_warns(capsys):
    _merge(dict(DEFAULTS), {"defaults": {}, "profiles": {}}, "typo", {}, {})
    assert "unknown profile" in capsys.readouterr().out
