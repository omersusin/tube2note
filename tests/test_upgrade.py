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

def test_incomplete_list_refetch(home):
    import time
    from tube2note.source import _list_load, _list_save, _LIST_INCOMPLETE_TTL
    _list_save(["u-inc"], 10, None, [{"id": "Y"}], "H", False)
    got, _ = _list_load(["u-inc"], 10, None)
    assert got == [{"id": "Y"}]
    import tube2note.source as s
    d = {"ts": time.time() - _LIST_INCOMPLETE_TTL - 1, "max_n": 10, "complete": False,
         "videos": [{"id": "Y"}], "hint": "H"}
    import json, os
    from tube2note.source import _list_cache_path
    p = _list_cache_path(["u-inc"], None)
    json.dump(d, open(p, "w", encoding="utf-8"))
    assert _list_load(["u-inc"], 10, None) is None
