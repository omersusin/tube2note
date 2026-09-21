import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fake_ydl  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HOME/config/cache so tests never touch the real ones."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
    monkeypatch.setenv("NO_COLOR", "1")
    from tube2note import config
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / ".config" / "yt2md" / "config.json"))
    return tmp_path


@pytest.fixture
def fake(home, monkeypatch):
    fake_ydl.CALLS["video_info"].clear()
    fake_ydl.CALLS["gemini"].clear()
    import tube2note.cli  # noqa: F401  (make sure submodules are imported so install() can patch them)
    fake_ydl.install(monkeypatch)
    return fake_ydl


@pytest.fixture
def run(fake, monkeypatch, capsys):
    """run("-o", "a.md", ...) -> stdout text. Runs the real CLI in-process against the fake yt-dlp."""
    from tube2note.cli import main

    def _run(*args):
        pace = [] if args and args[0] in ("status", "setup", "doctor", "pdf", "extras", "watch", "mcp", "search", "epub") else \
            ["--fetch-gap", "0", "--sleep", "0", "--verbose"]
        monkeypatch.setattr(sys, "argv", ["tube2note", *pace, *args])
        main()
        return capsys.readouterr().out
    return _run
