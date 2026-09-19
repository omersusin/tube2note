#!/usr/bin/env python3
"""tube2note: merge YouTube channel/playlist/video subtitles into Markdown files.
Usage:
  python3 tube2note.py -o notes.md "<playlist_url>" "<video_url>" ...
  python3 tube2note.py -o channel.md --max 50 --lang tr,en "https://www.youtube.com/@channel/videos"
  yt                        # guided interactive mode
  yt setup                  # personalize defaults (folder, layout, ...)
  python3 tube2note.py status [dir]   # progress table of saved collections
  python3 tube2note.py --dry-run "<playlist_url>"  # preview only, no download
Input: channel / playlist / single video URLs. Output: one Markdown file to feed NotebookLM.
Requires: pip install yt-dlp (no ffmpeg needed)
"""
import argparse
import datetime
import glob
import html
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import urllib.request

from yt_dlp import YoutubeDL

TAG_RE = re.compile(r"<[^>]+>")
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
UI_ON = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _len(s):
    return len(ANSI_RE.sub("", s))


def _pad(s, w):
    return s + " " * max(0, w - _len(s))


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if UI_ON else s


def bold(s):
    return _c("1", s)


def green(s):
    return _c("32", s)


def yellow(s):
    return _c("33", s)


def red(s):
    return _c("31", s)


def dim(s):
    return _c("2", s)


def cyan(s):
    return _c("36", s)


def panel(title, lines):
    rows = [title] + list(lines)
    w = max(_len(l) for l in rows)
    edge = "─" * (w + 2)
    out = [f"┌{edge}┐", f"│ {_pad(bold(title), w)} │", f"├{edge}┤"]
    out += [f"│ {_pad(l, w)} │" for l in lines]
    out.append(f"└{edge}┘")
    return "\n".join(out)


def table(headers, rows):
    widths = [_len(h) for h in headers]
    for r in rows:
        for j, c in enumerate(r):
            widths[j] = max(widths[j], _len(str(c)))
    sep = "─┼─".join("─" * w for w in widths)
    head = " │ ".join(_pad(bold(h), w) for h, w in zip(headers, widths))
    out = [head, sep]
    for r in rows:
        out.append(" │ ".join(_pad(str(c), w) for c, w in zip(r, widths)))
    return "\n".join(out)


def bar(frac, width=24):
    frac = max(0.0, min(1.0, frac))
    fill = int(frac * width)
    return f"[{'█' * fill}{'░' * (width - fill)}] {frac * 100:4.0f}%"


def _term_width():
    try:
        return max(40, shutil.get_terminal_size().columns)
    except Exception:
        return 80


def _short(s, w):
    s = str(s)
    return s if len(s) <= w else s[: max(0, w - 1)] + "…"


def _render_dash(done_n, todo_n, title, ok_n, skip_n, words, t0, status=""):
    """Pure: build the 3 dashboard lines (testable without a terminal)."""
    w = _term_width()
    el = (time.time() - t0) / 60
    frac = done_n / todo_n if todo_n else 0
    l1 = _short(f"{bar(frac)} {done_n}/{todo_n} · {words} words · {el:.0f} min", w)
    l2 = _short(f"▶ {title}", w)
    l3 = _short(f"ok {ok_n} · skipped {skip_n}" + (f" · {status}" if status else ""), w)
    return [l1, l2, l3]


_dash_lines = 0  # lines currently drawn (0 = nothing on screen yet)


_VERBOSE = False


def dash_update(done_n, todo_n, title, ok_n, skip_n, words, t0, status=""):
    """Redraw the single in-place dashboard (TTY) or plain lines (logs)."""
    global _dash_lines
    if _VERBOSE:
        el = (time.time() - t0) / 60
        extra = f" · {status}" if status else ""
        print(f"{done_n}/{todo_n} videos · {words} words · {el:.0f} min{extra}", flush=True)
        return
    if not UI_ON or todo_n <= 0:
        if todo_n > 0 and (done_n % 10 == 0 or done_n >= todo_n):
            print(f"{done_n}/{todo_n} videos · {words} words", flush=True)
        return
    lines = _render_dash(done_n, todo_n, title, ok_n, skip_n, words, t0, status)
    if _dash_lines:
        sys.stdout.write(f"\x1b[{_dash_lines}A")
    for l in lines:
        sys.stdout.write("\r\x1b[K" + l + "\n")
    sys.stdout.flush()
    _dash_lines = len(lines)


def log(msg):
    """Log line that cleanly breaks the live dashboard."""
    global _dash_lines
    if _dash_lines and UI_ON:
        sys.stdout.write("\n")
        _dash_lines = 0
    print(msg, flush=True)


def dash_end():
    global _dash_lines
    _dash_lines = 0


def _to_secs(t):
    try:
        p = t.strip().split(":")
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        return int(p[0]) * 60 + float(p[1])
    except (ValueError, IndexError, AttributeError):
        return 0.0


def _fmt_ts(s):
    s = int(s)
    h, m = s // 3600, s % 3600 // 60
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m:02d}:{s % 60:02d}"


def vtt_segments(vtt: str):
    """Parse VTT into [(start_secs, text)] with back-to-back dupes dropped."""
    segs, start = [], 0.0
    for block in vtt.splitlines():
        s = block.strip()
        if not s or s == "WEBVTT" or s.startswith("NOTE") or s.startswith("STYLE") or s.startswith("REGION"):
            continue
        if "-->" in s:
            start = _to_secs(s.split("-->")[0])
            continue
        if s.isdigit():
            continue
        s = TAG_RE.sub("", s)
        s = html.unescape(s).replace(" ", " ").strip()
        if s and (not segs or segs[-1][1] != s):  # drop back-to-back duplicates from auto captions
            segs.append((start, s))
    return segs


def _para_text(p, ts):
    body = " ".join(t for _, t in p)
    return f"[{_fmt_ts(p[0][0])}] {body}" if ts else body


def _join_paras(segs, ts=False, chapters=None):
    """Group segments into ~20-line paragraphs, or at the video's own chapter boundaries."""
    if chapters:
        ch = sorted(chapters)
        buckets, idx = [[] for _ in ch], 0
        for st, ln in segs:
            while idx + 1 < len(ch) and st >= ch[idx + 1][0]:
                idx += 1
            buckets[idx].append((st, ln))
        out = []
        for (st0, title), b in zip(ch, buckets):
            if not b:
                continue
            out.append(f"### {title}")
            out += [_para_text(b[i:i + 20], ts) for i in range(0, len(b), 20)]
        return "\n\n".join(out)
    paras, buf = [], []
    for i, seg in enumerate(segs, 1):
        buf.append(seg)
        if i % 20 == 0:
            paras.append(buf)
            buf = []
    if buf:
        paras.append(buf)
    return "\n\n".join(_para_text(p, ts) for p in paras)


def vtt_to_text(vtt: str, ts: bool = False) -> str:
    return _join_paras(vtt_segments(vtt), ts)


def _self_test():
    vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\nmerhaba <b>dünya</b>\n\n00:01.000 --> 00:02.000\nmerhaba <b>dünya</b>\n"
    assert vtt_to_text(vtt) == "merhaba dünya", vtt_to_text(vtt)
    assert vtt_to_text("WEBVTT\n\n00:01.500 --> 00:03.000\nhello\n", ts=True) == "[00:01] hello"
    class E(Exception):
        code = 429
    assert _is_throttle(E()) and not _is_throttle(ValueError())
    assert _is_throttle(Exception("HTTP Error 429: Too Many Requests"))
    assert _is_throttle(Exception("ERROR: [youtube] x: HTTP Error 429"))
    assert not _is_throttle(Exception("video abc429XYZ12 unavailable"))
    assert not _is_throttle(OSError("disk full"))
    assert _fold_latin1("Şarj ğü") == "Sarj gu"
    assert slug("PickY Audio!") == "picky-audio.md"
    assert _md_line_kind("## Hello") == ("h2", "Hello")
    assert _md_line_kind("- item") == ("bullet", "item")
    assert _md_line_kind("| a | b |")[0] == "row"
    assert _merge(dict(DEFAULTS), {"defaults": {"lang": "en"}, "profiles": {"p": {"lang": "de"}}},
                  "p", {"chunk": 5}, {"YT2MD_LANG": "fr"}) == {**DEFAULTS, "lang": "fr", "chunk": 5}
    assert _merge(dict(DEFAULTS), {"defaults": {}, "profiles": {"p": {"lang": "de"}}},
                  "p", {}, {})["lang"] == "de"
    assert sanitize_filename("a<b>c:.md") == "a-b-c-.md"
    assert sanitize_filename("CON") == "_CON"
    assert len(sanitize_filename("x" * 300).encode()) <= 200
    assert render_template("{channel}/{title} [{id}]", {"channel": "C", "title": "T", "id": "ID1"}) == "C/T [ID1].md"
    assert render_template("{nope}/x", {"a": "b"}) == "x.md"
    assert _unique_path("a/b.md", "ID1", {"a/b.md"}) == "a/b_ID1.md"
    assert _clean_text("eee hello um world world") == "hello world"
    try:
        _gemini_transcribe(b"x", "audio/mp3", "en")
        raise AssertionError("should need key")
    except SystemExit as e:
        assert "GEMINI_API_KEY" in str(e)
    assert _clean_text("good. Bad! Really? Yes.") == "good.\nBad!\nReally?\nYes."
    b = Bucket(rate=10, capacity=2)
    t = time.time()
    b.wait()
    b.wait()
    assert time.time() - t < 2
    segs = vtt_segments("WEBVTT\n\n00:00.500 --> 00:02.000\nhello\n\n00:02.000 --> 00:04.000\nworld\n")
    assert segs == [(0.5, "hello"), (2.0, "world")]
    chtext = _join_paras([(10.0, "a"), (70.0, "b"), (130.0, "c")], False, [(0, "Intro"), (60, "Main")])
    assert chtext.startswith("### Intro") and "### Main" in chtext and chtext.index("### Intro") < chtext.index("### Main")
    assert _parse_since("2024-01-15") > 0 and _parse_since("nope") == 0
    fm = _frontmatter("T", "u", "C", "ID", "en", False,
                      {"published": "2024-01-01", "duration": 60, "views": 5, "description": "d"})
    assert "published: 2024-01-01" in fm and "views: 5" in fm
    import tempfile
    td = tempfile.mkdtemp()
    os.environ["XDG_CACHE_HOME"] = td
    assert _get_vtt("VIDX", "en", False, [{"url": "http://x", "ext": "vtt"}],
                    lambda req: __import__("io").BytesIO(b"WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n")) == \
        ("WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n", False)
    assert _get_vtt("VIDX", "en", False, [{"url": "http://x", "ext": "vtt"}],
                    lambda req: 1 / 0) == ("WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n", True)
    assert _cache_path("V", "en", True) != _cache_path("V", "en", False)
    del os.environ["XDG_CACHE_HOME"]
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write('---\ntitle: "X"\nvideo_id: VID1\n---\n')
    assert _existing_vid(tf.name) == "VID1"
    assert _existing_vid(tf.name + ".missing") is None
    os.unlink(tf.name)
    d2 = tempfile.mkdtemp()
    p2 = os.path.join(d2, "s.skip")
    open(p2, "w", encoding="utf-8").write(
        json.dumps({"title": "Yeni Sarki | Official Video",
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "reason": "x"}) + "\n"
        "A | B | https://www.youtube.com/watch?v=DXhiKe37WLU | nope\n")
    assert _skip_map(p2) == {"dQw4w9WgXcQ": "x", "DXhiKe37WLU": "nope"}
    out, lim = [], 3
    _flatten(None, {"_type": "playlist",
                    "entries": [{"id": f"ABCDEFGHIJ{i}", "title": f"T{i}"} for i in range(5)]},
             out, lim)
    assert len(out) == 3 and out[0]["id"] == "ABCDEFGHIJ0"
    assert "50%" in bar(0.5) and bar(2.0).startswith("[█")
    assert "Name" in table(["Name", "Val"], [["a", "1"]])
    assert "tube2note" in panel("tube2note", ["x"])
    assert YT_RE.search("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not YT_RE.search("https://example.com/foo")
    d = _render_dash(1, 2, "hello world, this title is quite long", 1, 0, 10, time.time())
    assert len(d) == 3 and "50%" in d[0] and "hello" in d[1] and "ok 1" in d[2]
    log("test-line")
    dash_update(1, 1, "t", 1, 0, 5, time.time())
    dash_end()
    info = {"subtitles": {"en": [{"url": "http://x/v?lang=en&fmt=vtt", "ext": "vtt"}]},
            "automatic_captions": {"tr": [{"url": "http://x/?tlang=tr", "ext": "vtt"}]}}
    assert pick_sub(info, ["tr", "en"])[0] == "en"  # translated tracks must lose to originals
    print("self-test ok")


def _parse_since(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").timestamp()
    except (ValueError, TypeError):
        return 0


def _flatten(ydl, info, out, limit, depth=0, since_ts=0):
    """Channel -> tabs (Videos/Shorts/Live) -> videos, stopping at limit (so --max saves time)."""
    if len(out) >= limit:
        return
    entries = info.get("entries")
    if info.get("_type") not in ("playlist", "multi_video", "compat_batch") or not entries:
        vid = info.get("id") or ""
        if len(vid) == 11:  # video IDs are 11 chars; channels (UC..) / playlists (PL..) are not
            ts = info.get("timestamp") or info.get("release_timestamp") or 0
            if not (since_ts and ts and ts < since_ts):
                out.append({"id": vid, "title": info.get("title") or vid,
                            "channel": info.get("channel") or info.get("uploader"),
                            "url": f"https://www.youtube.com/watch?v={vid}"})
        return
    for e in entries:
        if len(out) >= limit:
            return
        if e is None:
            continue
        if e.get("entries"):
            _flatten(ydl, e, out, limit, depth + 1, since_ts)
        elif e.get("ie_key") == "Youtube" or len(e.get("id", "")) == 11:
            ts = e.get("timestamp") or e.get("release_timestamp") or 0
            if since_ts and ts and ts < since_ts:
                continue
            vid = e.get("id")
            out.append({"id": vid, "title": e.get("title") or vid,
                        "channel": e.get("channel") or e.get("uploader"),
                        "url": f"https://www.youtube.com/watch?v={vid}"})
        elif depth < 2 and e.get("url"):
            try:
                sub = ydl.extract_info(e["url"], download=False)
            except Exception:
                continue
            if sub:
                _flatten(ydl, sub, out, limit, depth + 1, since_ts)


def expand(urls, max_n, since=None):
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "socket_timeout": 20}
    out, hint = [], None
    since_ts = _parse_since(since) if since else 0
    with YoutubeDL(ydl_opts) as ydl:
        for u in urls:
            try:
                info = ydl.extract_info(u, download=False)
            except Exception as e:
                print(f"! could not list {u}: {e}", file=sys.stderr)
                continue
            if not info:
                continue
            if hint is None and len(urls) == 1 and info.get("title"):
                hint = info.get("title")
            _flatten(ydl, info, out, max_n, since_ts=since_ts)
            if len(out) >= max_n:
                break
    # dedupe in case the same video came from two lists
    seen, uniq = set(), []
    for v in out:
        if v["id"] not in seen:
            seen.add(v["id"])
            uniq.append(v)
    return uniq[:max_n], hint


def pick_sub(info, langs):
    # ponytail: original tracks only; tlang translations are the most 429-prone kind
    subs, autos = info.get("subtitles") or {}, info.get("automatic_captions") or {}
    for pool in (subs, autos):
        for lg in langs:
            if lg in pool:
                fmts = [f for f in pool[lg] if "tlang=" not in (f.get("url") or "")]
                if fmts:
                    return lg, fmts, pool is autos
    return None, None, False


def _make_req(url):
    """yt-dlp Request when available (silences its urlopen deprecation), else stdlib."""
    try:
        from yt_dlp.networking.common import Request as YdlRequest
        return YdlRequest(url, headers={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})


def fetch_vtt(formats, opener=None):
    want = [f for f in formats if f.get("ext") == "vtt"] or formats
    # ponytail: ilk vtt'yi al, tum formatlari denemek gereksiz
    url = want[0]["url"]
    req = _make_req(url)
    if opener is None:  # plain stdlib (tests, offline use)
        ctx = urllib.request.urlopen(req, timeout=20)
    else:  # yt-dlp handler: proxy, cookies, impersonation aware
        ctx = opener(req)
    with ctx as r:
        return r.read().decode("utf-8", errors="ignore")


def _is_throttle(e):
    # yt-dlp wraps HTTP errors in DownloadError/ExtractorError WITHOUT .code,
    # but the message keeps "HTTP Error 429: ..." — check both.
    if getattr(e, "code", None) in (429, 500, 502, 503):
        return True
    msg = str(e)
    return re.search(r"\b429\b", msg) is not None or "Too Many Requests" in msg


class Bucket:
    """Thread-safe token bucket: max `rate` timedtext fetches/sec, `capacity` burst."""

    def __init__(self, rate, capacity):
        self.rate, self.capacity = rate, capacity
        self.tokens, self.stamp = capacity, time.monotonic()
        self.lock = threading.Lock()

    def wait(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.stamp) * self.rate)
                self.stamp = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                pause = (1 - self.tokens) / self.rate
            time.sleep(min(pause, 1.0))


def _countdown(secs, label, tick=None):
    # long breaks: plain lines in logs, live status line on TTY via tick()
    if secs <= 0:
        return
    if not UI_ON:
        print(f"{label}: sleeping ~{secs // 60} min...", flush=True)
        time.sleep(secs)
        print(f"{label}: done.", flush=True)
        return
    end = time.time() + max(1, secs)
    while True:
        left = int(end - time.time())
        if left <= 0:
            break
        if tick:
            tick(left)
        time.sleep(min(5, left))


def slug(s, fallback="tube2note"):
    s = re.sub(r"[^a-z0-9]+", "-", sanitize_filename(s, "").lower()).strip("-")
    return (s[:60] or fallback) + ".md"


WIN_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def sanitize_filename(s, fallback="untitled"):
    """Cross-platform safe single path segment (Windows/macOS/Linux/Android)."""
    tr = str.maketrans("şğüöçıİŞĞÜÖÇ", "sguociisguoc")
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "-", (s or "").translate(tr)).strip(" .")
    if s.lower() in WIN_RESERVED:
        s = "_" + s
    s = (s or fallback).encode("utf-8")[:200].decode("utf-8", "ignore")
    return s or fallback


DEFAULT_TEMPLATES = {
    "single": None,
    "videos": "videos/{title} [{id}]",
    "tree": "{channel}/{title}/transcript",
}


_WARNED_FIELDS = set()


def render_template(tmpl, fields):
    """Fill {field} placeholders; unknown fields become empty (warned once). Sanitize per segment."""
    fields = fields or {}
    unknown = set(re.findall(r"\{(\w+)\}", tmpl or "")) - set(fields)
    new = unknown - _WARNED_FIELDS
    if new:
        _WARNED_FIELDS.update(new)
        print(f"warning: unknown template field(s): {', '.join(sorted(new))} (left empty)", flush=True)
    rel = re.sub(r"\{(\w+)\}", lambda m: str(fields.get(m.group(1), "")), tmpl or "")
    segs = [sanitize_filename(p) for p in rel.split("/") if p.strip() and p.strip() != "."]
    rel = "/".join(segs)
    if rel and not rel.lower().endswith(".md"):
        rel += ".md"
    return rel or "untitled.md"


def detect_langs(videos, probe=3, want=("tr", "en")):
    """Sample the first few videos for ORIGINAL subtitle languages: (suggestion, found).
    tlang translations are ignored (most 429-prone kind)."""
    direct, anykey = {}, {}
    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                    "socket_timeout": 20}) as ydl:
        for v in videos[:probe]:
            try:
                info = ydl.extract_info(v["url"], download=False)
            except Exception:
                continue
            for pool in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
                for k, fmts in pool.items():
                    anykey[k] = anykey.get(k, 0) + 1
                    if any("tlang=" not in (f.get("url") or "") for f in fmts):
                        direct[k] = direct.get(k, 0) + 1
    shown = sorted(direct) or sorted(anykey)
    for pool in (direct, anykey):
        for w in want:
            if w in pool:
                return w, shown
    for pool in (direct, anykey):
        if pool:
            return sorted(pool, key=lambda k: -pool[k])[0], shown
    return "tr,en", []


def split_output(out, budget):
    """Split a finished md into <=budget-word parts at video boundaries. Returns part paths."""
    raw = open(out, encoding="utf-8").read()
    head, sep, body = raw.partition("---\n\n")
    head = head + sep if sep else ""
    sections = [s for s in body.split("---\n\n") if s.strip()]
    base, ext = os.path.splitext(out)
    parts, cur, curw, idx = [], [], 0, 0
    for s in sections:
        w = len(s.split())
        if cur and curw + w > budget:
            parts.append((idx + 1, cur))
            cur, curw, idx = [], 0, idx + 1
        cur.append(s)
        curw += w
    if cur:
        parts.append((idx + 1, cur))
    if len(parts) <= 1:
        return []
    paths = []
    for i, secs in parts:
        lines = head.split("\n")
        if lines:
            lines[0] += f" (part {i}/{len(parts)})"
        p = f"{base}_part{i:02d}{ext}"
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("---\n\n".join(secs)) + "---\n")
        paths.append(p)
    return paths


YT_RE = re.compile(r"(youtube\.com/(watch|shorts|playlist|@|channel/|c/|user/|live|embed)|youtu\.be/|[?&](list|v)=)")


def show_intro():
    print(panel("tube2note — YouTube to NotebookLM", [
        "Turn a channel, playlist or videos into Markdown + PDF.",
        "",
        "  HOW TO USE:",
        "  1. Paste link(s) and press Enter",
        "  2. Check the auto-detected summary table",
        "  3. Answer 2-3 questions (all have defaults)",
        "  4. Wait — the dashboard shows everything",
        "  5. Upload the .md (or _part files) to NotebookLM",
        "",
        "  TIPS: Ctrl+C stops safely, resume anytime.",
        "  Big file? Type 400000 at the split prompt.",
        "  More: 'yt setup' (defaults), 'yt status' (progress).",
        "",
        dim("NotebookLM cap: 500,000 words per source file."),
    ]))


def is_first_run():
    p = os.path.expanduser("~/.config/yt2md/seen")
    if os.path.exists(p):
        return False
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("1")
    except OSError:
        return False
    return True


def show_guide():
    print(panel("Quick guide", [
        "Paste any YouTube link: channel, playlist or video.",
        "The tool lists videos, guesses the file name + languages.",
        "Big jobs run in chunks with breaks (anti-429 protection).",
        "Progress is saved: Ctrl+C anytime, resume later.",
        "When done, upload the .md (or _part files) to NotebookLM.",
    ]))


CONFIG_PATH = os.path.expanduser("~/.config/yt2md/config.json")
DEFAULTS = {"outdir": ".", "layout": "single", "timestamps": False, "chunk": 50,
            "chunk_cooldown_min": 10, "lang": "tr,en", "template": "", "clean": True}

ENV_MAP = {"outdir": "YT2MD_OUTDIR", "layout": "YT2MD_LAYOUT", "lang": "YT2MD_LANG",
           "chunk": "YT2MD_CHUNK", "timestamps": "YT2MD_TIMESTAMPS",
           "chunk_cooldown_min": "YT2MD_COOLDOWN_MIN", "template": "YT2MD_TEMPLATE",
           "clean": "YT2MD_CLEAN"}


def load_config():
    """Config file: {"defaults": {...}, "profiles": {name: {...}}}. Old flat files count as defaults."""
    raw = {}
    try:
        data = json.load(open(CONFIG_PATH, encoding="utf-8"))
        if isinstance(data, dict):
            raw = data
    except (OSError, ValueError, TypeError):
        pass
    if "defaults" in raw or "profiles" in raw:
        defaults, profiles = raw.get("defaults") or {}, raw.get("profiles") or {}
    else:
        defaults, profiles = raw, {}
    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(profiles, dict):
        profiles = {}
    store = {"defaults": defaults, "profiles": profiles}
    for k, v in raw.items():  # keep runtime keys like "last", "last:<profile>"
        if k not in store:
            store[k] = v
    return store


def save_config(store):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    json.dump(store, open(CONFIG_PATH, "w", encoding="utf-8"), indent=2)


def _merge(base, store, profile, flags, env):
    """Precedence: flags > env > profile > config defaults > builtins. Pure (testable)."""
    cfg = dict(base)
    cfg.update({k: v for k, v in store.get("defaults", {}).items() if k in base})
    if profile and profile in store.get("profiles", {}):
        cfg.update({k: v for k, v in store["profiles"][profile].items() if k in base})
    for key, var in ENV_MAP.items():
        if env.get(var, "") != "":
            cfg[key] = env[var]
    cfg.update({k: v for k, v in flags.items() if v is not None})
    for key in ("chunk", "chunk_cooldown_min"):
        try:
            cfg[key] = max(0, int(cfg[key]))
        except (ValueError, TypeError):
            cfg[key] = base[key]
    for key in ("timestamps", "clean"):
        if isinstance(cfg.get(key), str):
            cfg[key] = cfg[key].lower() in ("1", "y", "yes", "true")
    if cfg.get("layout") not in ("single", "videos", "tree"):
        cfg["layout"] = base["layout"]
    return cfg


def resolve_config(flags=None, profile=None):
    return _merge(dict(DEFAULTS), load_config(), profile, flags or {}, dict(os.environ))


def cmd_setup(advanced=False):
    """Personalize: 3 sticky defaults (folder, layout, language); pacing under --advanced."""
    store = load_config()
    cfg = _merge(dict(DEFAULTS), store, None, {}, {})
    print(panel("Personalize tube2note", ["CLI flags and YT2MD_* env vars always win over these."]))
    cfg["outdir"] = input(f"Default folder [{cfg['outdir']}] > ").strip() or cfg["outdir"]
    lay = input(f"Output layout (single/videos/tree) [{cfg['layout']}] > ").strip().lower() or cfg["layout"]
    cfg["layout"] = lay if lay in ("single", "videos", "tree") else "single"
    cfg["lang"] = input(f"Default languages [{cfg['lang']}] > ").strip() or cfg["lang"]
    if advanced:
        ts = input(f"Timestamps? (y/n) [{'y' if cfg['timestamps'] else 'n'}] > ").strip().lower()
        if ts in ("y", "yes", "n", "no"):
            cfg["timestamps"] = ts in ("y", "yes")
        try:
            cfg["chunk"] = max(0, int(input(f"Chunk size [{cfg['chunk']}] > ").strip() or cfg["chunk"]))
        except ValueError:
            pass
        try:
            cfg["chunk_cooldown_min"] = max(0, int(input(f"Chunk break minutes [{cfg['chunk_cooldown_min']}] > ").strip()
                                                    or cfg["chunk_cooldown_min"]))
        except ValueError:
            pass
        cfg["template"] = input(f"Name template [{cfg['template'] or 'layout default'}] > ").strip()
    store["defaults"] = {k: cfg[k] for k in DEFAULTS if k in cfg}
    name = input("Save as profile name [skip] > ").strip()
    if name:
        store.setdefault("profiles", {})[name] = dict(store["defaults"])
        print(f"Profile '{name}': use with --profile {name} or YT2MD_PROFILE={name}")
    save_config(store)
    print(green("Saved to ") + CONFIG_PATH)
    return cfg


def tui():
    prof = os.environ.get("YT2MD_PROFILE") or None
    cfg = resolve_config(profile=prof)
    show_intro()
    if is_first_run():
        show_guide()
        if input("Personalize defaults now? (folder, layout...) [Y/n] > ").strip().lower() not in ("n", "no"):
            cfg = cmd_setup()
    while True:
        raw = input("\nURLs (space/comma separated, several allowed) > ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            return
        urls = [u.strip(" ,") for u in re.split(r"[,\s]+", raw) if u.strip(" ,")]
        if not urls:
            print("No URLs, try again.")
            continue
        bad = [u for u in urls if not YT_RE.search(u)]
        if bad:
            print(red("Not a YouTube link: ") + ", ".join(bad))
            continue
        since = input("Only videos since YYYY-MM-DD [any] > ").strip() or None
        print("Listing videos, wait...")
        videos, hint = expand(urls, 5000, since)
        if not videos:
            print("No videos found.")
            continue
        guess = slug(hint)
        print("Sampling subtitle languages...")
        sug, found = detect_langs(videos)
        est = len(videos) * 12 / 60
        print(table(["Setting", "Value"], [
            ["Source", (hint or urls[0])[:60]],
            ["Videos", str(len(videos))],
            ["File", guess],
            ["Languages", sug + (f"  (found: {', '.join(found[:8])})" if found else "")],
            ["Est. time", f"~{est:.0f} min paced" if est >= 1 else "<1 min"],
        ]))
        out = input(f"Output file [{guess}] > ").strip() or guess
        outdir = input(f"Folder [{cfg['outdir']}] > ").strip() or cfg["outdir"]
        lay = input(f"Layout (single/videos/tree) [{cfg['layout']}] > ").strip().lower() or cfg["layout"]
        lay = lay if lay in ("single", "videos", "tree") else "single"
        lang = input(f"Languages [{sug}] > ").strip() or sug
        mx = input(f"Max videos [{len(videos)}] > ").strip() or str(len(videos))
        try:
            max_n = max(1, int(mx))
        except ValueError:
            max_n = len(videos)
        videos = videos[:max_n]
        ch = input(f"Chunk size [{cfg['chunk']}] > ").strip() or str(cfg["chunk"])
        try:
            ch = max(0, int(ch))
        except ValueError:
            ch = cfg["chunk"]
        cd = input(f"Chunk break minutes [{cfg['chunk_cooldown_min']}] > ").strip() or str(cfg["chunk_cooldown_min"])
        try:
            chc = max(0, int(cd)) * 60
        except ValueError:
            chc = cfg["chunk_cooldown_min"] * 60
        yn = "y" if cfg["timestamps"] else "n"
        ts = input(f"Timestamps? [{yn}] > ").strip().lower()
        ts = cfg["timestamps"] if ts == "" else ts in ("y", "yes")
        cl = input(f"Cleaning? [{'y' if cfg['clean'] else 'n'}] > ").strip().lower()
        cl = cfg["clean"] if cl == "" else cl in ("y", "yes")
        pdf = input("PDF too? [n] > ").strip().lower() in ("y", "yes")
        tmp = input(f"Name template [{cfg['template'] or 'layout default'}] > ").strip()
        tmp = tmp or cfg["template"]
        wk = input("Workers [1] > ").strip() or "1"
        try:
            wk = min(4, max(1, int(wk)))
        except ValueError:
            wk = 1
        sp = input("Auto-split words for NotebookLM [0=off] > ").strip() or "0"
        try:
            sp = max(0, int(sp))
        except ValueError:
            sp = 0
        print(f"\n{len(videos)} videos, output: {outdir}/{out}, langs: {lang}, layout: {lay}, "
              f"chunk: {ch}/{chc // 60}min, timestamps: {ts}, template: {tmp or 'default'}, split: {sp or 'off'}")
        go = input("[Enter]=start, q=cancel > ").strip()
        if go.lower() in ("q", "quit"):
            continue
        try:
            run_job(urls, out, lang, max_n, 2.0, False, ch, chc, 1800, videos, outdir, ts, sp,
                    layout=lay, template=tmp, pdf=pdf, since=since, profile=prof, workers=wk,
                    clean=cl)
        except KeyboardInterrupt:
            print("\nCancelled.")
        again = input("\nNew job? [Enter]=yes, q=quit > ").strip()
        if again.lower() in ("q", "quit", "exit"):
            return


def _frontmatter(title, wurl, channel, vid, lg, auto, meta=None):
    def clean(s):
        s = " ".join(str(s).split()).replace('"', "'").replace("\\", "/")
        return s.lstrip("-?:,{}[]&*!|>#%@` ").strip() or "unknown"
    t = clean(title or vid)
    c = clean(channel or "unknown")
    out = (f"---\ntitle: \"{t}\"\nsource: {wurl}\nchannel: \"{c}\"\n"
           f"video_id: {vid}\nlanguage: {lg}{' (auto)' if auto else ''}\n")
    if meta:
        if meta.get("method"):
            out += f"method: {meta['method']}\n"
        if meta.get("published"):
            out += f"published: {meta['published']}\n"
        if meta.get("duration") is not None:
            out += f"duration_secs: {meta['duration']}\n"
        if meta.get("views") is not None:
            out += f"views: {meta['views']}\n"
        if meta.get("description"):
            out += f"description: \"{clean(meta['description'][:500])}\"\n"
    return out + "---\n\n"


def _video_meta(info):
    """Free metadata from the per-video extract (no extra requests)."""
    ud = info.get("upload_date") or ""
    pub = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}" if len(ud) == 8 else ""
    return {"published": pub, "duration": info.get("duration"),
            "views": info.get("view_count"), "description": info.get("description") or ""}


def _existing_vid(path):
    """Read video_id from an existing per-video file's frontmatter (None if unknown)."""
    try:
        with open(path, encoding="utf-8") as f:
            for i, ln in enumerate(f):
                if i > 12:
                    break
                m = re.match(r"video_id:\s*(\S+)", ln)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _unique_path(vp, vid, used):
    """Disambiguate slug collisions: second same-named file gets _<video_id>."""
    if vp in used:
        base, ext = os.path.splitext(vp)
        vp = f"{base}_{vid}{ext}"
    used.add(vp)
    return vp


def _count_lines(path):
    try:
        return sum(1 for ln in open(path, encoding="utf-8") if ln.strip())
    except OSError:
        return 0


def _skip_map(skip_log):
    """Parse skip lines into {video_id_or_url: reason}. JSON first, legacy 'a | b | c' via right-split."""
    m = {}
    try:
        lines = open(skip_log, encoding="utf-8")
    except OSError:
        return m
    with lines:
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            try:
                d = json.loads(s)
                t, u, r = d.get("title", ""), d.get("url", ""), d.get("reason", "")
            except (ValueError, AttributeError):
                parts = [p.strip() for p in s.rsplit(" | ", 2)]
                if len(parts) != 3:
                    continue
                t, u, r = parts
            m2 = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", u or "")
            m[m2.group(1) if m2 else u] = r
    return m


def _write_index(root, videos, completed, words_by_id, skip_log):
    """INDEX.md: every video with status, words and per-video file."""
    reasons = _skip_map(skip_log)
    rows = []
    for v in videos:
        vid = v["id"]
        st = "done" if vid in completed else reasons.get(vid, "pending")
        rows.append([v.get("title") or vid, st, str(words_by_id.get(vid, "-"))])
    with open(os.path.join(root, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write(f"# Index\n\n- Videos: {len(videos)}\n- Done: {len(completed)}\n\n")
        f.write(table(["Title", "Status", "Words"], rows))


COLLECTION_KEYS = ("layout", "lang", "timestamps", "chunk", "chunk_cooldown_min")


def _collection_override(root):
    """Per-collection .yt2md.json overrides (safe subset only)."""
    try:
        data = json.load(open(os.path.join(root, ".yt2md.json"), encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in COLLECTION_KEYS if k in data}


def _md_line_kind(line):
    """Classify one markdown line for the PDF renderer (pure, testable)."""
    s = line.rstrip("\n")
    if s.startswith("## "):
        return ("h2", s[3:].strip())
    if s.startswith("# "):
        return ("h1", s[2:].strip())
    if s.strip() in ("---", "***"):
        return ("rule", "")
    if s.lstrip().startswith("- "):
        return ("bullet", s.lstrip()[2:].strip())
    if s.strip().startswith("|") and s.strip().endswith("|"):
        return ("row", "  ".join(c.strip() for c in s.strip().strip("|").split("|")))
    return ("para", s.strip())


TR_FOLD = str.maketrans("şŞğĞüÜöÖçÇıİ", "sSgGuUoOcCiI")


def _fold_latin1(s):
    """Best-effort Turkish-preserving fold into latin-1 (for core PDF fonts)."""
    return s.translate(TR_FOLD).encode("latin-1", "replace").decode("latin-1")


def _pdf_font(pdf):
    """(font_name, unicode_ok, bold_ok). Prefers a Unicode TTF (Turkish glyphs)."""
    for p in ("/system/fonts/DroidSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/data/data/com.termux/files/usr/share/fonts/DejaVuSans.ttf"):
        if not os.path.exists(p):
            continue
        try:
            pdf.add_font("body", "", p)
        except Exception:
            continue
        bold_ok = False
        try:
            b = p.replace(".ttf", "-Bold.ttf")
            pdf.add_font("body", "B", b if os.path.exists(b) else p)
            bold_ok = True
        except Exception:
            pass
        return "body", True, bold_ok
    return "helvetica", False, True


def md_to_pdf(md_path, pdf_path=None):
    """Convert our Markdown to PDF. Needs fpdf2 (pip install fpdf2) — optional dep."""
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError:
        raise SystemExit("PDF needs fpdf2: pip install fpdf2  (or pip install tube2note[pdf])")
    pdf_path = pdf_path or os.path.splitext(md_path)[0] + ".pdf"
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=20)
    font, uni, bold_ok = _pdf_font(pdf)
    if not uni:
        print("warning: no Unicode font found — non-latin glyphs will be folded to ASCII", flush=True)
    pdf.add_page()
    pdf.set_font(font, size=11)
    # ponytail: fpdf2 2.8 leaves the cursor at the right margin after
    # multi_cell; force LMARGIN or the next line has zero width and crashes.
    def mc(h, t, s=11, st=""):
        pdf.set_font(font, st if (st != "B" or bold_ok) else "", s)
        pdf.multi_cell(0, h, t if uni else _fold_latin1(t),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for raw in open(md_path, encoding="utf-8").read().splitlines():
        if not raw.strip():
            pdf.ln(3)
            continue
        kind, text = _md_line_kind(raw)
        if kind == "h1":
            mc(8, text, 16, "B")
            pdf.set_font(font, size=11)
        elif kind == "h2":
            mc(7, text, 13, "B")
            pdf.set_font(font, size=11)
        elif kind == "rule":
            pdf.ln(2)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
        elif kind == "bullet":
            mc(6, "• " + text)
        else:
            mc(6, text)
    pdf.output(pdf_path)
    return pdf_path


def _cache_path(vid, lg, auto=False):
    base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    kind = "auto" if auto else "man"
    return os.path.join(base, "tube2note", "subs", f"{vid}.{lg}.{kind}.vtt")


def _get_vtt(vid, lg, auto, fmts, opener, fetch_gap=10):
    """Shared subtitle cache: same video is never downloaded twice (429-friendly).
    The key includes the track kind so a later manual upload replaces stale auto text."""
    p = _cache_path(vid, lg, auto)
    if os.path.exists(p):
        try:
            return open(p, encoding="utf-8").read(), True
        except OSError:
            pass
    time.sleep(random.uniform(1, max(1, fetch_gap)))  # pace timedtext fetches only
    vtt = fetch_vtt(fmts, opener)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(vtt)
    except OSError:
        pass
    return vtt, False


FILLER_RE = re.compile(r"\b(um|uh|er|ah|mm|hmm|eee|ee|ıı)\b", re.IGNORECASE)
DUP_RE = re.compile(r"\b(.+?)(\s+\1\b)+", re.IGNORECASE)
ABBR_RE = re.compile(r"\b(Mr|Mrs|Dr|Jr|St)\.")
NUMDOT_RE = re.compile(r"(\d)\.(\d)")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZİŞĞÜÖÇ0-9\"“])")


def _clean_text(text):
    """Cheap transcript cleanup: fillers, repeated phrases, one sentence per line."""
    out = []
    for para in text.split("\n\n"):
        tag, body = "", para
        m = re.match(r"(\[\d+:?\d*:\d+\]\s*)", body)
        if m:
            tag, body = m.group(1), body[m.end():]
        body = FILLER_RE.sub("", body)
        prev = None
        while prev != body:
            prev, body = body, DUP_RE.sub(r"\1", body)
        body = ABBR_RE.sub(r"\1<<prd>>", body)
        body = NUMDOT_RE.sub(r"\1<<prd>>\2", body)
        sents = [s.replace("<<prd>>", ".").strip(" ,") for s in SENT_SPLIT_RE.split(body)]
        sents = [re.sub(r"\s{2,}", " ", s).strip() for s in sents if s.strip()]
        if sents:
            out.append(tag + "\n".join(sents))
    return "\n\n".join(out)


AUDIO_MIMES = {"mp3": "audio/mp3", "wav": "audio/wav", "aac": "audio/aac",
               "ogg": "audio/ogg", "flac": "audio/flac", "m4a": "audio/mp4",
               "webm": "audio/webm"}
AUDIO_MAX_BYTES = 18 * 1024 * 1024


def _download_audio(vid, tmpdir):
    """Audio-only download, no ffmpeg: returns (path, ext) or (None, reason)."""
    import tempfile
    out = os.path.join(tmpdir, vid + ".%(ext)s")
    opts = {"quiet": True, "no_warnings": True, "skip_download": False,
            "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "outtmpl": out, "socket_timeout": 30}
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid}"])
    except Exception as e:
        return None, str(e) or type(e).__name__
    for f in os.listdir(tmpdir):
        if f.startswith(vid + "."):
            return os.path.join(tmpdir, f), f.rsplit(".", 1)[-1].lower()
    return None, "audio file not found"


def _gemini_transcribe(audio_bytes, mime, lang="en", model="gemini-2.0-flash"):
    """Send audio to Gemini API, return verbatim transcript. Needs GEMINI_API_KEY."""
    import base64
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("transcribe needs GEMINI_API_KEY (free at aistudio.google.com)")
    body = json.dumps({
        "contents": [{"parts": [
            {"text": f"Transcribe this audio verbatim in {lang}. Output only the transcript text, no commentary."},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio_bytes).decode()}}]}],
        "generationConfig": {"temperature": 0.0}}).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=body, headers={"Content-Type": "application/json"})
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=120))
    except Exception as e:
        raise RuntimeError(f"Gemini API error: {e}")
    try:
        return resp["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Gemini API unexpected response: {str(resp)[:200]}")


def _try_transcribe(vid, lang, tmpdir):
    """Captionless fallback: audio download + Gemini. Returns (text, note) or (None, reason)."""
    import tempfile
    path, ext = _download_audio(vid, tmpdir)
    if path is None:
        return None, ext
    try:
        if ext not in AUDIO_MIMES:
            return None, f"audio format .{ext} not accepted by API"
        if os.path.getsize(path) > AUDIO_MAX_BYTES:
            return None, "audio too large for API (>18MB)"
        with open(path, "rb") as f:
            text = _gemini_transcribe(f.read(), AUDIO_MIMES[ext], lang)
        if len(text) < 50:
            return None, "transcript too short"
        return text, "transcribed via Gemini"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _fetch_unit(ydl_opts, v, langs, ts, bucket, fetch_gap, clean=True,
                transcribe=False, tmpdir=None):
    """One video, network only, never raises (except disk-full).
    Returns dict with stage: extract|subs|fetch|ok."""
    res = {"v": v, "title": v.get("title") or v["id"], "wurl": v.get("url"),
           "channel": v.get("channel"), "lg": None, "auto": False,
           "text": None, "error": None, "throttled": False,
           "stage": "extract", "chapters": [], "meta": {}}
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(v["url"], download=False)
            res["title"] = info.get("title") or res["title"]
            res["wurl"] = info.get("webpage_url") or res["wurl"]
            res["channel"] = res["channel"] or info.get("channel")
            lg, fmts, auto = pick_sub(info, langs)
            if not fmts:
                if transcribe:
                    ttext, note = _try_transcribe(v["id"], langs[0] if langs else "en", tmpdir)
                    if ttext is not None:
                        res.update(lg=langs[0] if langs else "en", auto=False, text=ttext,
                                   trans=True, stage="ok")
                        res["meta"]["method"] = "gemini-transcribe"
                        return res
                    res["error"] = f"no subtitles ({note})"
                else:
                    res["error"] = "no subtitles"
                res["stage"] = "subs"
                return res
            res.update(lg=lg, auto=auto)
            res["chapters"] = [(c.get("start_time") or 0, c.get("title") or "")
                               for c in (info.get("chapters") or []) if c.get("title")]
            res["meta"] = _video_meta(info)
            last = None
            for _ in (1, 2):  # ponytail: 60s + ONE retry on 429; hot retries extend the ban
                try:
                    if bucket is not None:
                        bucket.wait()
                    vtt, cached = _get_vtt(v["id"], lg, auto, fmts, ydl.urlopen,
                                          0 if bucket is not None else fetch_gap)
                    res["text"] = _join_paras(vtt_segments(vtt), ts, res["chapters"] or None).strip()
                    if clean:
                        res["text"] = _clean_text(res["text"])
                    res["cached"] = cached
                    res["stage"] = "ok"
                    return res
                except Exception as e:
                    last = e
                    if getattr(e, "errno", None) == 28:
                        raise
                    if not _is_throttle(e):
                        break
                    time.sleep(60)
            res["error"] = f"subtitle download failed: {last}"
            res["throttled"] = _is_throttle(last)
            res["stage"] = "fetch"
            return res
    except Exception as e:
        if getattr(e, "errno", None) == 28:
            raise
        res["error"] = str(e) or type(e).__name__
        res["throttled"] = _is_throttle(e)
        return res


def _stream(ydl_opts, work, langs, ts, bucket, workers, fetch_gap, clean=True,
            transcribe=False, tmpdir=None):
    """Yield (i, v, res) in submission order; purely serial when workers<=1."""
    if workers <= 1:
        for i, v in work:
            yield i, v, _fetch_unit(ydl_opts, v, langs, ts, None, fetch_gap, clean,
                                    transcribe, tmpdir)
        return
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(i, v, ex.submit(_fetch_unit, ydl_opts, v, langs, ts, bucket, fetch_gap,
                                 clean, transcribe, tmpdir)) for i, v in work]
        for i, v, fu in futs:
            try:
                yield i, v, fu.result()
            except Exception as e:
                if getattr(e, "errno", None) == 28:
                    raise
                yield i, v, {"v": v, "title": v.get("title") or v["id"], "wurl": v.get("url"),
                             "channel": v.get("channel"), "lg": None, "auto": False,
                             "text": None, "error": str(e) or type(e).__name__,
                             "throttled": _is_throttle(e), "stage": "extract",
                             "chapters": [], "meta": {}}


def run_job(urls, out, lang_str, max_n, sleep, fresh=False, chunk=50, chunk_cooldown=600,
            throttle_cooldown=1800, videos=None, outdir=".", ts=False, split_words=0,
            verbose=False, layout="single", template="", pdf=False,
            proxy=None, cookiefile=None, since=None, profile=None, fetch_gap=10,
            workers=1, clean=True, transcribe=False):
    if videos is None:
        videos, _ = expand(urls, max_n, since)
    if outdir and outdir != ".":
        outdir = os.path.expanduser(outdir)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, out)
    root = os.path.dirname(os.path.abspath(out))
    coll = _collection_override(root)
    if coll.get("layout") in ("single", "videos", "tree"):
        layout = coll["layout"]
    if isinstance(coll.get("lang"), str) and coll["lang"].strip():
        lang_str = coll["lang"]
    if isinstance(coll.get("timestamps"), bool):
        ts = coll["timestamps"]
    if coll.get("chunk") is not None:
        try:
            chunk = max(0, int(coll["chunk"]))
        except (ValueError, TypeError):
            pass
    if coll.get("chunk_cooldown_min") is not None:  # minutes, like the TUI prompt
        try:
            chunk_cooldown = max(0, int(coll["chunk_cooldown_min"])) * 60
        except (ValueError, TypeError):
            pass
    langs = [s.strip() for s in lang_str.split(",") if s.strip()]
    total = len(videos)
    if transcribe and not os.environ.get("GEMINI_API_KEY", ""):
        print("transcribe needs GEMINI_API_KEY (free at aistudio.google.com) — stopping before any work.")
        return
    _save_last(urls=urls, out=os.path.basename(out),
               outdir=os.path.dirname(os.path.abspath(out)) or ".", lang=lang_str,
               max_n=max_n, chunk=chunk, chunk_cooldown=chunk_cooldown, layout=layout,
               template=template, ts=ts, split_words=split_words, sleep=sleep,
               since=since, proxy=proxy, cookiefile=cookiefile, profile=profile)
    print(f"{total} videos found", flush=True)
    if not videos:
        return
    done_log, skip_log = out + ".done", out + ".skip"
    done = set()
    if not fresh and os.path.exists(done_log):
        with open(done_log, encoding="utf-8") as f:
            done = {ln.strip() for ln in f if ln.strip()}
        print(f"resuming: {len(done)} videos already done", flush=True)
    fresh_start = fresh or not os.path.exists(out)
    mode = "w" if fresh_start else "a"
    fout = open(out, mode, encoding="utf-8")
    dlog = open(done_log, "w" if fresh_start else "a", encoding="utf-8")
    slog = open(skip_log, "w" if fresh_start else "a", encoding="utf-8")
    wlog = open(out + ".words", "w" if fresh_start else "a", encoding="utf-8")
    if fresh_start:
        done = set()
    if mode == "w":
        today = datetime.date.today().isoformat()
        fout.write(f"# YouTube Research Notes\n\n- Date: {today}\n- Videos: target {total}\n"
                   f"- Languages: {','.join(langs)}\n\nFeed this file to NotebookLM as a source.\n\n---\n\n")
    todo = max(0, total - len(done))
    completed = set(done)
    words_by_id = {}
    if not fresh_start and os.path.exists(out + ".words"):
        try:
            for ln in open(out + ".words", encoding="utf-8"):
                p = ln.split()
                if len(p) == 2:
                    words_by_id[p[0]] = int(p[1])
        except (OSError, ValueError):
            pass
    print(f"target: {todo} videos (chunk: {chunk}, chunk break: {chunk_cooldown // 60} min, layout: {layout})", flush=True)
    ok, skip, words, consec, since_break, status = 0, [], 0, 0, 0, ""
    used_paths = set()
    global _VERBOSE
    _VERBOSE = verbose
    t0 = time.time()
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "writesubtitles": False, "socket_timeout": 20,
                "subtitlesformat": "vtt/best",
                "extractor_args": {"youtube": {"skip": ["translated_subs"]}}}
    if proxy:
        ydl_opts["proxy"] = proxy
    if cookiefile:
        ydl_opts["cookiefile"] = os.path.expanduser(cookiefile)
    bucket = Bucket(rate=0.15, capacity=2) if workers > 1 else None
    work = [(i, v) for i, v in enumerate(videos, 1) if v["id"] not in done]
    tmpdir = tempfile.mkdtemp(prefix="tube2note-")
    if workers > 1:
        print(f"parallel mode: {workers} workers sharing one bucket (~1 fetch/7s)", flush=True)
    with YoutubeDL(ydl_opts) as ydl:
        for i, v, res in _stream(ydl_opts, work, langs, ts, bucket, workers, fetch_gap,
                                clean, transcribe, tmpdir):
            if chunk > 0 and since_break >= chunk and (ok + len(skip)) < todo:
                if verbose:
                    log(f"--- CHUNK done, {chunk_cooldown // 60} min break ---")
                _countdown(chunk_cooldown, "chunk break", lambda left: dash_update(
                    ok + len(skip), todo, v["title"], ok, len(skip), words, t0,
                    status=f"chunk break {left // 60:02d}:{left % 60:02d} left"))
                status = ""
                since_break = 0
            since_break += 1
            dash_update(ok + len(skip), todo, f"[{i}/{total}] {v['title']}",
                        ok, len(skip), words, t0, status)
            if verbose:
                log(f"[{i}/{total}] {v['title'][:70]}")
            if res["stage"] == "extract":
                if verbose:
                    log(f"  ! skipped: {res['error']}")
                skip.append((v["title"], v["url"], res["error"]))
                consec = consec + 1 if res["throttled"] else 0
                status = "throttled" if res["throttled"] else "extract failed"
                if consec >= 5:
                    if verbose:
                        log("  ! 5 throttles in a row -> long cooldown")
                    _countdown(throttle_cooldown, "throttle cooldown", lambda left: dash_update(
                        ok + len(skip), todo, v["title"], ok, len(skip), words, t0,
                        status=f"throttle cooldown {left // 60:02d}:{left % 60:02d} left"))
                    consec, status = 0, ""
                continue
            title, wurl, lg, auto = res["title"], res["wurl"], res["lg"], res["auto"]
            if res["stage"] == "subs":
                if verbose:
                    log("  ! no subtitles, skipped")
                skip.append((title, wurl, "no subtitles"))
                consec, status = 0, "no subtitles"
                continue
            text = res["text"]
            if res.get("cached") and verbose:
                log("  (from cache)")
            if text is None:
                if verbose:
                    log(f"  ! subtitle download failed: {res['error']}")
                skip.append((title, wurl, res["error"]))
                consec = consec + 1 if res["throttled"] else 0
                status = "throttled" if res["throttled"] else "subtitle failed"
                if consec >= 5:
                    if verbose:
                        log("  ! 5 throttles in a row -> long cooldown")
                    _countdown(throttle_cooldown, "throttle cooldown", lambda left: dash_update(
                        ok + len(skip), todo, title, ok, len(skip), words, t0,
                        status=f"throttle cooldown {left // 60:02d}:{left % 60:02d} left"))
                    consec, status = 0, ""
                continue
            consec, status = 0, ""
            if len(text) < 50:
                skip.append((title, wurl, "subtitle too short"))
                consec, status = 0, "subtitle too short"
                continue
            try:
                fout.write(f"## {i}. {title}\n\n- Source: {wurl}\n"
                           f"- Video ID: {v['id']}\n- Subtitle lang: {lg}"
                           f"{' (transcribed)' if res.get('trans') else (' (auto)' if auto else '')}\n\n{text}\n\n---\n\n")
                fout.flush()
                dlog.write(v["id"] + "\n")
                dlog.flush()
                ok += 1
                nwords = len(text.split())
                words += nwords
                completed.add(v["id"])
                done.add(v["id"])
                words_by_id[v["id"]] = nwords
                wlog.write(f"{v['id']} {nwords}\n")
                wlog.flush()
                if layout != "single":
                    fields = {"channel": v.get("channel") or res.get("channel") or "channel",
                              "title": title or v["id"], "id": v["id"],
                              "index": f"{i:02d}", "date": datetime.date.today().isoformat(),
                              "lang": lg}
                    vp = _unique_path(os.path.join(root, render_template(
                        template or DEFAULT_TEMPLATES[layout], fields)), v["id"], used_paths)
                    if _existing_vid(vp) not in (None, v["id"]):
                        # another session's different video owns this path: do not overwrite
                        base, ext = os.path.splitext(vp)
                        vp = f"{base}_{v['id']}{ext}"
                        used_paths.add(vp)
                    os.makedirs(os.path.dirname(vp), exist_ok=True)
                    with open(vp, "w", encoding="utf-8") as vf:
                        vf.write(_frontmatter(title, wurl, v.get("channel") or res.get("channel"),
                                              v["id"], lg, auto, res.get("meta")))
                        vf.write(f"## {title}\n\n{text}\n")
            except OSError as e:
                print(red(f"  ! FATAL disk/IO error, stopping: {e}"))
                raise SystemExit(1)
            dash_update(ok + len(skip), todo, v["title"], ok, len(skip), words, t0)
            time.sleep(sleep)
    dash_update(todo, todo, "done", ok, len(skip), words, t0)
    dash_end()
    for t, u, s in skip:
        slog.write(json.dumps({"title": t, "url": u, "reason": s}, ensure_ascii=False) + "\n")
    fout.close()
    dlog.close()
    slog.close()
    wlog.close()
    shutil.rmtree(tmpdir, ignore_errors=True)
    if layout != "single":
        _write_index(root, videos, completed, words_by_id, skip_log)
        print(f"index: {os.path.join(root, 'INDEX.md')}", flush=True)
    try:  # reconcile .skip: drop fixed videos + dedupe, so counts/tail stay honest
        seen, kept = set(), []
        if os.path.exists(skip_log):
            for ln in open(skip_log, encoding="utf-8"):
                s = ln.strip()
                if not s:
                    continue
                r = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", s)
                key = r.group(1) if r else s
                if key not in completed and key not in seen:
                    seen.add(key)
                    kept.append(s)
        with open(skip_log, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
    except OSError:
        pass
    ndone = _count_lines(done_log)
    nskip = _count_lines(skip_log)
    if ndone + nskip >= len(videos):
        if nskip > 0:
            tail_done = False
            try:
                with open(out, "rb") as _f:
                    _f.seek(max(0, os.path.getsize(out) - 5000))
                    tail_done = b"## Skipped" in _f.read()
            except OSError:
                pass
            if not tail_done:
                with open(out, "a", encoding="utf-8") as f:
                    f.write("\n## Skipped\n\n")
                    for ln in open(skip_log, encoding="utf-8"):
                        s = ln.strip()
                        if not s:
                            continue
                        try:
                            d = json.loads(s)
                            f.write(f"- [{d.get('title', '?')}]({d.get('url', '')}) — {d.get('reason', '')}\n")
                        except ValueError:
                            f.write(f"- {s}\n")
        dash_end()
        print(panel("Done", [
            f"{green(str(ndone))} videos -> {out} ({nskip} skipped)",
            f"~{words} words this run",
        ]))
        if split_words > 0:
            total_words = len(open(out, encoding="utf-8").read().split())
            if total_words > split_words:
                parts = split_output(out, split_words)
                if len(parts) > 1:
                    print(panel("Upload to NotebookLM", ["Add each part as a separate source:"]
                                + [f"  {j}. {p}" for j, p in enumerate(parts, 1)]))
                else:
                    print(f"Single file is enough ({total_words} words).")
            else:
                print(f"No split needed ({total_words} words <= {split_words}).")
        else:
            print("Upload to NotebookLM: add this file as a source.")
            print(dim("Cap is 500,000 words/file — use --split-words if bigger."))
        if pdf:
            base, _ = os.path.splitext(out)
            for src in [out] + sorted(glob.glob(base + "_part*.md")):
                try:
                    print("PDF: " + md_to_pdf(src), flush=True)
                except SystemExit as e:
                    print(e)
                    break
    else:
        dash_end()
        print(f"Checkpoint: {ok} videos, {words} words -> {out} (total: {ndone}/{len(videos)})")


def cmd_doctor(proxy=None):
    """Environment diagnosis: versions, fonts, config, disk."""
    rows = []
    try:
        import yt_dlp.version as yv
        rows.append(["yt-dlp installed", yv.__version__])
    except Exception as e:
        rows.append(["yt-dlp installed", f"missing ({e})"])
    latest, note = _pypi_latest("yt-dlp", proxy)
    rows.append(["yt-dlp latest (PyPI)", latest + note])
    try:
        import fpdf
        rows.append(["fpdf2 (PDF)", fpdf.__version__])
    except Exception:
        rows.append(["fpdf2 (PDF)", "missing — pip install tube2note[pdf]"])
    font_ok = any(os.path.exists(p) for p in
                  ("/system/fonts/DroidSans.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                   "/data/data/com.termux/files/usr/share/fonts/DejaVuSans.ttf"))
    rows.append(["Unicode font (PDF Turkish)", "found" if font_ok else "MISSING — PDF folds to ASCII"])
    try:
        load_config()
        rows.append(["config file", "parse ok"])
    except Exception as e:
        rows.append(["config file", f"BROKEN: {e}"])
    try:
        free = shutil.disk_usage(os.path.expanduser("~"))[2] // (1024 ** 3)
        rows.append(["disk free (home)", f"{free} GB"])
    except Exception as e:
        rows.append(["disk free (home)", f"unknown ({e})"])
    print(panel("tube2note doctor", []))
    print(table(["Check", "Result"], rows))


def _pypi_latest(pkg, proxy=None):
    """(version, note): weekly-cached PyPI lookup, never fatal."""
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                         "tube2note", "pypi.json")
    try:
        d = json.load(open(cache, encoding="utf-8"))
        if time.time() - d.get("ts", 0) < 7 * 86400 and d.get(pkg):
            return d[pkg], " (cached)"
    except (OSError, ValueError):
        pass
    try:
        req = urllib.request.Request(f"https://pypi.org/pypi/{pkg}/json",
                                     headers={"User-Agent": "tube2note-doctor"})
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            d2 = json.load(opener.open(req, timeout=15))
        else:
            d2 = json.load(urllib.request.urlopen(req, timeout=15))
        ver = d2["info"]["version"]
        try:
            old = {}
            try:
                old = json.load(open(cache, encoding="utf-8"))
            except (OSError, ValueError):
                pass
            old.update({"ts": time.time(), pkg: ver})
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            json.dump(old, open(cache, "w", encoding="utf-8"))
        except OSError:
            pass
        return ver, ""
    except Exception as e:
        return "unknown", f" ({e})"


def cmd_widget():
    """Write a Termux:Widget shortcut that resumes the last collection in one tap."""
    dst = os.path.expanduser("~/.shortcuts/tube2note")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("#!/data/data/com.termux/files/usr/bin/bash\n"
                "# Termux:Widget shortcut — resume last tube2note collection\n"
                'if command -v tube2note >/dev/null; then exec tube2note --resume-last; '
                'else exec python3 "$HOME/yt2md/tube2note.py" --resume-last; fi\n')
    os.chmod(dst, 0o755)
    print(f"Widget written to {dst} (needs Termux:Widget app).")


def _save_last(profile=None, **kw):
    try:
        store = load_config()
        store["last:" + profile if profile else "last"] = kw
        save_config(store)
    except OSError:
        pass


def cmd_status(d="."):
    d = os.path.expanduser(d)
    try:
        files = sorted(os.listdir(d))
    except OSError as e:
        print(f"Cannot list {d}: {e}")
        return
    rows = []
    for f in files:
        if not f.endswith(".md") or "_part" in f:
            continue
        path = os.path.join(d, f)
        dn = _count_lines(path + ".done")
        sk = _count_lines(path + ".skip")
        rows.append([f, str(dn), str(sk), f"{os.path.getsize(path) // 1024} KB"])
    if not rows:
        print(f"No collections in {d}.")
        return
    print(table(["Collection", "Done", "Skipped", "Size"], rows))


def cmd_dryrun(urls, max_n, lang_str):
    videos, hint = expand(urls, max_n)
    if not videos:
        print("No videos found.")
        return
    sug, found = detect_langs(videos)
    est = len(videos) * 12 / 60
    print(table(["Setting", "Value"], [
        ["Source", (hint or urls[0])[:60]],
        ["Videos", str(len(videos))],
        ["Languages", sug + (f"  (found: {', '.join(found[:8])})" if found else "")],
        ["Est. time", f"~{est:.0f} min paced" if est >= 1 else "<1 min"],
        ["Est. words", f"~{len(videos) * 2000} (rough: ~2k/video)"],
    ]))
    print("Dry run: nothing downloaded. Drop --dry-run to start.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        cmd_status(sys.argv[2] if len(sys.argv) > 2 else ".")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        cmd_setup("--advanced" in sys.argv)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        px = None
        if "--proxy" in sys.argv:
            i = sys.argv.index("--proxy")
            px = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        cmd_doctor(px)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "widget":
        cmd_widget()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "pdf":
        if len(sys.argv) < 3:
            print("Usage: tube2note.py pdf <file.md> [...]")
            return
        for f in sys.argv[2:]:
            try:
                print("PDF: " + md_to_pdf(f), flush=True)
            except (OSError, SystemExit) as e:
                print(f"! {f}: {e}")
        return
    ap = argparse.ArgumentParser(description="YouTube -> single Markdown (NotebookLM feed)")
    ap.add_argument("urls", nargs="*", help="channel / playlist / video URLs")
    ap.add_argument("-o", "--out", default="tube2note.md")
    ap.add_argument("--lang", default=None, help="subtitle language priority, comma separated")
    ap.add_argument("--max", type=int, default=100, help="max number of videos")
    ap.add_argument("--sleep", type=float, default=2.0, help="pause between videos (s)")
    ap.add_argument("--chunk", type=int, default=None, help="long break every N videos")
    ap.add_argument("--chunk-cooldown", type=int, default=None, help="break between chunks (s)")
    ap.add_argument("--fetch-gap", type=int, default=None, help="max pause before subtitle fetch, seconds (default 10)")
    ap.add_argument("--workers", type=int, default=1, help="parallel fetch workers 1-4 (default 1, serial and safest)")
    ap.add_argument("--throttle-cooldown", type=int, default=1800, help="break after 5 throttles in a row (s)")
    ap.add_argument("-d", "--dir", default=None, help="output folder (created if missing)")
    ap.add_argument("--layout", default=None, help="output layout: single, videos or tree")
    ap.add_argument("--timestamps", action="store_true", default=None, help="keep [MM:SS] markers in transcripts")
    ap.add_argument("--clean", dest="clean", action="store_true", default=None, help="clean transcripts (default on)")
    ap.add_argument("--no-clean", dest="clean", action="store_false", help="keep raw transcripts")
    ap.add_argument("--since", default=None, help="only videos published on/after YYYY-MM-DD")
    ap.add_argument("--resume-last", action="store_true", help="re-run the last saved collection job")
    ap.add_argument("--name-template", default=None, help='per-video path template, e.g. "{channel}/{title} [{id}]"')
    ap.add_argument("--profile", default=None, help="config profile name (or YT2MD_PROFILE)")
    ap.add_argument("--split-words", type=int, default=0, help="auto-split finished file into N-word parts (0=off)")
    ap.add_argument("--pdf", action="store_true", help="also write PDF next to the Markdown (needs fpdf2)")
    ap.add_argument("--transcribe", action="store_true", help="transcribe captionless videos via Gemini API (needs GEMINI_API_KEY)")
    ap.add_argument("--proxy", default=None, help="proxy URL for all requests (yt-dlp syntax, e.g. socks5://127.0.0.1:1080)")
    ap.add_argument("--cookies", default=None, help="Netscape cookies.txt file (helps logged-in/age-gated content)")
    ap.add_argument("--tui", action="store_true", help="interactive mode (short command)")
    ap.add_argument("--verbose", action="store_true", help="scrolling log lines instead of the live dashboard")
    ap.add_argument("--dry-run", action="store_true", help="list + estimate only, download nothing")
    ap.add_argument("--fresh", action="store_true", help="discard previous progress, start over")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return
    if a.tui or not a.urls:
        try:
            tui()
        except (KeyboardInterrupt, EOFError):
            print("\nExit.")
        return
    profile = a.profile or os.environ.get("YT2MD_PROFILE") or None
    cfg = resolve_config({"outdir": a.dir, "layout": a.layout, "lang": a.lang,
                          "chunk": a.chunk, "timestamps": a.timestamps,
                          "chunk_cooldown_min": (a.chunk_cooldown // 60
                                                 if a.chunk_cooldown is not None else None),
                          "template": a.name_template, "clean": a.clean}, profile)
    fetch_gap = a.fetch_gap if a.fetch_gap is not None else 10
    workers = min(4, max(1, a.workers or 1))
    if a.dry_run:
        cmd_dryrun(a.urls, a.max, cfg["lang"])
        return
    if a.resume_last:
        store = load_config()
        last = (store.get("last:" + profile) if profile else None) or store.get("last")
        if not last or not last.get("urls"):
            ap.error("no saved job: run once first (resume info is stored automatically)")
        run_job(last["urls"], last.get("out", "tube2note.md"), last.get("lang", cfg["lang"]),
                last.get("max_n", 100), last.get("sleep", 2.0), False, last.get("chunk", 50),
                last.get("chunk_cooldown", 600), a.throttle_cooldown,
                outdir=last.get("outdir", "."), ts=last.get("ts", False),
                split_words=last.get("split_words", 0), verbose=a.verbose,
                layout=last.get("layout", "single"), template=last.get("template", ""),
                pdf=a.pdf, proxy=last.get("proxy"), cookiefile=last.get("cookiefile"),
                since=last.get("since"))
        return
    run_job(a.urls, a.out, cfg["lang"], a.max, a.sleep, a.fresh, cfg["chunk"],
            cfg["chunk_cooldown_min"] * 60, a.throttle_cooldown, outdir=cfg["outdir"],
            ts=cfg["timestamps"], split_words=a.split_words, verbose=a.verbose,
            layout=cfg["layout"], template=cfg["template"], pdf=a.pdf,
            proxy=a.proxy, cookiefile=a.cookies, since=a.since, profile=profile,
            fetch_gap=fetch_gap, workers=workers, clean=cfg["clean"],
            transcribe=a.transcribe)


if __name__ == "__main__":
    main()