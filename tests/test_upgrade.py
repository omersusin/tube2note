import io
import json
import time

from tube2note.config import DEFAULTS, _merge
from tube2note.source import (
    _LIST_INCOMPLETE_TTL,
    _list_cache_path,
    _list_load,
    _list_save,
    fetch_vtt,
)
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
    _list_save(["u-inc"], 10, None, [{"id": "Y"}], "H", False)
    got, _ = _list_load(["u-inc"], 10, None)
    assert got == [{"id": "Y"}]
    d = {"ts": time.time() - _LIST_INCOMPLETE_TTL - 1, "max_n": 10, "complete": False,
         "videos": [{"id": "Y"}], "hint": "H"}
    p = _list_cache_path(["u-inc"], None)
    json.dump(d, open(p, "w", encoding="utf-8"))
    assert _list_load(["u-inc"], 10, None) is None

def test_retry_after_hint():
    from tube2note.throttle import _retry_after_hint as H

    class E(Exception):
        def __init__(self, msg="", headers=None):
            super().__init__(msg)
            self.headers = headers
    assert H(E("429 Retry-After: 120"), 60) == 120
    assert H(E("HTTP Error 429", {"Retry-After": "600"}), 60) == 600
    assert H(E("boom"), 60) == 60
    assert H(E("Retry-After: soon"), 60) == 60
    assert H(E("Retry-After: Wed, 21 Oct 2015 07:28:00 GMT"), 60) == 60
    assert H(E("Retry-After: 5"), 60) == 60
    assert H(E("Retry-After: 999999"), 60) == 7200
    assert H(E("Retry-After: 0"), 60) == 60 and H(E("Retry-After: -3"), 60) == 60
    assert H(E("Retry-After: 120, 120"), 60) == 120
    assert H("plain string Retry-After: 90", 60) == 90 and H(None, 60) == 60
    assert H(E("x", {"Retry-After": None}), 60) == 60
    assert H(E("x", {"retry-after": "30"}), 10) == 30
