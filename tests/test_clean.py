import pytest

from tube2note import clean as t
from tube2note import llm


@pytest.mark.parametrize("text,lang,expected", [
    ("um hello world world", "en", "hello world"),
    ("this, uh, works", "en", "this, works"),
    ("eee merhaba ee dünya", "tr", "merhaba dünya"),
    ("you know you know it works", "en", "you know it works"),
    # "er"/"um" are real words in German/Portuguese/Dutch: never strip them
    ("Er ist um drei Uhr zurück.", "de", "Er ist um drei Uhr zurück."),
    ("Ele disse um dia.", "pt", "Ele disse um dia."),
    ("Er ist um drei Uhr zurück.", None, "Er ist um drei Uhr zurück."),
    ("good. Bad! Really? Yes.", "en", "good.\nBad!\nReally?\nYes."),
    ("Hello Dr. Smith. Pi is 3.14 ok.", "en", "Hello Dr. Smith.\nPi is 3.14 ok."),
])
def test_clean_text(text, lang, expected):
    assert t._clean_text(text, lang) == expected


def test_lang_variants_share_filler_list():
    assert t._clean_text("um yes", "en-US") == "yes"
    assert t._clean_text("um yes", "en_GB") == "yes"


def test_collapse_repeats_is_linear():
    n = 20000
    big = " ".join(f"w{i}" for i in range(n)) + "."
    out = t._clean_text(big, "en")
    flat = out.replace("\n", " ")
    assert len(flat.split()) == n  # no token lost
    assert flat.startswith("w0 w1") and flat.endswith(f"w{n-1}.")
    rep = t._clean_text(" ".join(["hello"] * n) + ".", "en")
    assert len(rep.split()) <= t.DUP_MAX_WORDS + 2  # collapsed, not O(n) output
    assert t.DUP_MAX_WORDS <= 6  # op bound: n * DUP_MAX <= 120k gram checks
    assert n * t.DUP_MAX_WORDS <= 120000


def test_gemini_key_never_in_url(monkeypatch):
    import json
    import urllib.request
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}).encode()

    def fake(req, timeout=0):
        seen["url"], seen["hdr"] = req.full_url, req.get_header("X-goog-api-key")
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert llm._gemini_request("SECRET", {"contents": []}) == "ok"
    assert "SECRET" not in seen["url"] and seen["hdr"] == "SECRET"
