"""Watch mode, MCP server, extras install/remove (all offline)."""
import sys

import pytest


def test_watch_new_videos_filter():
    from tube2note.watch import _new_videos
    vids = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert [v["id"] for v in _new_videos(vids, {"a"})] == ["b", "c"]
    assert _new_videos(vids, {"a", "b", "c"}) == []


def test_watch_seen_roundtrip(home):
    from tube2note import watch
    p = watch._state_path(["http://x"], "w.md")
    assert watch._load_seen(p) == set()
    watch._save_seen(p, {"a", "b"})
    assert watch._load_seen(p) == {"a", "b"}


def test_watch_cli_collects_only_new(home, monkeypatch, capsys):
    import tube2note.cli as cli
    import tube2note.watch as w
    listed = [{"id": "v1", "title": "Old", "url": "http://v1"},
              {"id": "v2", "title": "New", "url": "http://v2"}]
    monkeypatch.setattr(w, "expand", lambda urls, max_n, fresh=False: (listed, None))
    calls = []
    monkeypatch.setattr(w, "run_job",
                        lambda urls, *a, **k: calls.append(urls) or {"ok": 2, "skipped": 0, "total": 2})
    monkeypatch.setattr(sys, "argv", ["tube2note", "watch", "http://ch", "-o", "w.md", "--sleep", "0"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    assert calls == [["http://v1", "http://v2"]]  # first run: nothing seen yet
    # second run: all seen -> no job
    calls.clear()
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["tube2note", "watch", "http://ch", "-o", "w.md", "--sleep", "0"])
    with pytest.raises(SystemExit) as e2:
        cli.main()
    assert e2.value.code == 0 and calls == []
    assert "no new videos" in capsys.readouterr().out


def test_watch_fatal_keeps_seen(home, monkeypatch):
    import tube2note.watch as w
    monkeypatch.setattr(w, "expand", lambda urls, max_n, fresh=False: ([{"id": "v9", "url": "u"}], None))
    monkeypatch.setattr(w, "run_job", lambda *a, **k: {"ok": 0, "skipped": 0, "total": 0})  # fatal: throttled out
    import argparse
    args = argparse.Namespace(max=30, sleep=0, throttle_cooldown=1, verbose=False,
                              pdf=False, proxy=None, cookies=None, timestamps=False,
                              link_timestamps=False, srt=False)
    from tube2note.config import resolve_config
    cfg = resolve_config({}, None)
    assert w._check(["http://ch"], "w.md", cfg, args) == 1
    assert w._load_seen(w._state_path(["http://ch"], "w.md")) == set()


def test_mcp_handshake():
    from tube2note.mcp import TOOLS, _handle
    r, _ = _handle({"id": 1, "method": "initialize", "params": {}})
    assert r["result"]["serverInfo"]["name"] == "tube2note"
    r, _ = _handle({"id": 2, "method": "tools/list", "params": {}})
    assert {t["name"] for t in r["result"]["tools"]} == {"download", "status", "dry_run"}
    assert TOOLS  # advertised schemas exist
    r, _ = _handle({"id": 3, "method": "ping", "params": {}})
    assert r["result"] == {}
    r, _ = _handle({"id": 4, "method": "nope", "params": {}})
    assert r["error"]["code"] == -32601
    r, _ = _handle({"method": "notifications/initialized"})
    assert r is None


def test_mcp_status_and_unknown_tool(home):
    from tube2note.mcp import _handle
    r, _ = _handle({"id": 1, "method": "tools/call",
                    "params": {"name": "status", "arguments": {"dir": str(home)}}})
    assert "No collections" in r["result"]["content"][0]["text"]
    r, _ = _handle({"id": 2, "method": "tools/call",
                    "params": {"name": "bogus", "arguments": {}}})
    assert r["result"]["isError"]


def test_mcp_download_dispatch(monkeypatch):
    import tube2note.job as job
    from tube2note.mcp import _handle
    monkeypatch.setattr(job, "run_job", lambda *a, **k: {"ok": 1, "skipped": 0, "total": 1})
    r, _ = _handle({"id": 1, "method": "tools/call",
                    "params": {"name": "download", "arguments": {"url": "http://v"}}})
    assert "exit=0" in r["result"]["content"][0]["text"]


def test_extras_registry_and_unknown(home, capsys):
    from tube2note.commands import EXTRAS, cmd_extras, ensure_extra
    assert set(EXTRAS) >= {"pdf", "whisper", "faster-whisper"}
    assert ensure_extra("nope") is False
    cmd_extras(["install", "nope"])
    assert "unknown extra" in capsys.readouterr().out
    cmd_extras(["remove", "nope"])
    assert "unknown extra" in capsys.readouterr().out
    out = cmd_extras([])
    assert out is None
    assert "faster-whisper" in capsys.readouterr().out


def test_watch_partial_run_retries(home, monkeypatch):
    import tube2note.watch as w
    monkeypatch.setattr(w, "expand", lambda urls, max_n, **k: ([{"id": "v1", "url": "u1"},
                                                              {"id": "v2", "url": "u2"}], None))
    monkeypatch.setattr(w, "run_job", lambda *a, **k: {"ok": 1, "skipped": 1, "total": 2})
    import argparse
    args = argparse.Namespace(max=30, sleep=0, throttle_cooldown=1, verbose=False,
                              pdf=False, proxy=None, cookies=None, timestamps=False,
                              link_timestamps=False, srt=False)
    from tube2note.config import resolve_config
    assert w._check(["http://ch"], "w.md", resolve_config({}, None), args) == 1
    assert w._load_seen(w._state_path(["http://ch"], "w.md")) == set()  # partial: retry next round


def test_mcp_nondict_request():
    from tube2note.mcp import _handle
    r, _ = _handle([])
    assert r["error"]["code"] == -32600
    r, _ = _handle(None)
    assert r["error"]["code"] == -32600


def test_search_bad_encoding_skipped(home):
    from tube2note.search import search_collections
    (home / "bad.md").write_bytes(b"# T\n\n\xff\xfe binary \x00 junk hello\n")
    assert search_collections("hello", str(home)) == 0


def test_subs_bom_and_indent(home):
    from tube2note.subs import load_subs
    p = home / "subs.yaml"
    p.write_bytes(b"\xef\xbb\xbf- url: http://a\n  out: a.md\n")
    assert load_subs(str(p)) == [{"url": "http://a", "out": "a.md"}]
    p.write_text("  - url: http://b\n    out: b.md\n", encoding="utf-8")
    assert load_subs(str(p)) == [{"url": "http://b", "out": "b.md"}]


def test_ip_blocked_variants():
    from tube2note.throttle import _is_throttle
    assert _is_throttle(Exception("IP blocked"))
    assert _is_throttle(Exception("your IP address has been blocked"))
    assert not _is_throttle(Exception("video abc429XYZ12 unavailable"))


def test_watch_subs_file(home, monkeypatch):
    import tube2note.watch as w
    (home / "subs.yaml").write_text("- url: http://a\n  out: a.md\n  lang: en\n"
                                     "- url: http://b\n  out: b.md\n", encoding="utf-8")
    monkeypatch.setattr(w, "expand", lambda urls, max_n, **k: ([{"id": "v1", "title": "T",
                                                                "url": urls[0]}], None))
    seen = []
    monkeypatch.setattr(w, "run_job",
                        lambda urls, *a, **k: seen.append((urls, k.get("outdir"))) or
                        {"ok": 1, "skipped": 0, "total": 1})
    import sys
    monkeypatch.setattr(sys, "argv", ["tube2note"])
    code = w.cmd_watch(["--subs", str(home / "subs.yaml"), "-d", str(home), "--sleep", "0"])
    assert code == 0
    assert [u for u, _ in seen] == [["http://a"], ["http://b"]]  # each sub collected to its own out
