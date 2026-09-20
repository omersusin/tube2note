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
    assert os.path.exists(os.path.join(ROOT, "docs", "app.html"))
    assert os.path.exists(os.path.join(ROOT, "docs", "app.js"))
    assert "fetch" in open(os.path.join(ROOT, "docs", "sw.js")).read()
    assert json.load(open(os.path.join(ROOT, "docs", "manifest.webmanifest")))["name"]

def test_server_api_import():
    import importlib.util
    assert importlib.util.find_spec("tube2note.server_api") is not None
