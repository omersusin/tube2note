import json
import os

from tube2note.config import DEFAULTS, _merge
from tube2note.throttle import _is_throttle
from tube2note.web import build_argv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_throttle_bot():
    assert _is_throttle(Exception("Sign in to confirm you're not a bot"))
    assert not _is_throttle(ValueError("x"))

def test_profile_warn(capsys):
    _merge(dict(DEFAULTS), {"defaults": {}, "profiles": {}}, "typo", {}, {})
    assert "unknown profile" in capsys.readouterr().out

def test_build_argv_caps(tmp_path):
    try:
        build_argv({"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"] * 51}, str(tmp_path))
        raise AssertionError("should cap 50")
    except ValueError as e:
        assert "50" in str(e)

def test_build_argv_ssrf(tmp_path):
    try:
        build_argv({"urls": ["http://169.254.169.254/"]}, str(tmp_path))
        raise AssertionError("should reject")
    except ValueError:
        pass

def test_pwa_files():
    import re
    sw = open(os.path.join(ROOT, "docs", "sw.js")).read()
    assert 'startsWith("/api/")' in sw and 'startsWith("/files/")' in sw  # never cache API
    assert "fetch" in sw and "caches.match" in sw
    shell = re.search(r"SHELL\s*=\s*\[(.*?)\]", sw, re.S).group(1)
    files = re.findall(r'"([^"]+)"', shell)
    assert len(files) >= 4
    for f in files:
        assert os.path.exists(os.path.join(ROOT, "docs", f.lstrip("./"))), f
    assert json.load(open(os.path.join(ROOT, "docs", "manifest.webmanifest")))["name"]
    # app.html ids cover backend keys (split id maps to split_words payload key)
    html = open(os.path.join(ROOT, "docs", "app.html"), encoding="utf-8").read()
    ids = set(re.findall(r'id="([^"]+)"', html))
    from tube2note.web import INDEX_HTML
    mf = re.search(r'const FIELDS=\[(.*?)\]', INDEX_HTML, re.S).group(1)
    mb = re.search(r'const BOOLS=\[(.*?)\]', INDEX_HTML, re.S).group(1)
    backend = set(re.findall(r'"([^"]+)"', mf + mb)) | {"dry_run"}
    alias = {"split_words": "split"}
    for k in backend:
        assert k in ids or alias.get(k) in ids or k == "dry_run", k

def test_server_api_import():
    import ast
    src = open(os.path.join(ROOT, "tube2note", "server_api.py"), encoding="utf-8").read()
    for r in ("/api/start", "/api/stop", "/api/state", "/api/download", "/healthz"):
        assert r in src, r
    assert 'return {"ok": True}' in src  # healthz open
    assert "secrets.compare_digest" in src and "token_urlsafe" in src
    assert "64 * 1024" in src and "len(urls) > 50" in src
    fns = {n.name for n in ast.walk(ast.parse(src))
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {"healthz", "start", "stop", "state", "dl", "_auth", "_ok"} <= fns
