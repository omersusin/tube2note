"""Listing channels/playlists via yt-dlp, subtitle picking and the shared subtitle cache."""
import datetime
import json
import os
import random
import re
import sys
import time
import urllib.request

from yt_dlp import YoutubeDL


def _say(*a, **k):
    """Pipe-safe print: stderr when stdout is a data pipe."""
    import sys

    from . import ui as _u
    if _u.PIPE:
        print(*a, file=sys.stderr, flush=True)
    else:
        print(*a, **k)


def _parse_since(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").timestamp()
    except (ValueError, TypeError):
        return 0


def _flatten(ydl, info, out, limit, depth=0, since_ts=0):
    """Channel -> tabs (Videos/Shorts/Live) -> videos, stopping at limit (so --max saves time)."""
    limit = limit or 100
    if not isinstance(info, dict):
        return
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
        if isinstance(e, str):  # bare URL strings in flat playlists
            if ydl is not None and len(out) < limit:
                try:
                    sub = ydl.extract_info(e, download=False)
                except Exception:
                    continue
                if sub:
                    _flatten(ydl, sub, out, limit, depth + 1, since_ts)
            continue
        if not isinstance(e, dict):
            continue
        if e.get("entries"):
            _flatten(ydl, e, out, limit, depth + 1, since_ts)
        elif e.get("ie_key") == "Youtube" or len(e.get("id") or "") == 11:
            ts = e.get("timestamp") or e.get("release_timestamp") or 0
            if since_ts and ts and ts < since_ts:
                continue
            vid = e.get("id")
            out.append({"id": vid, "title": e.get("title") or vid,
                        "channel": e.get("channel") or e.get("uploader"),
                        "url": f"https://www.youtube.com/watch?v={vid}"})
        elif depth < 3 and e.get("url") and ydl is not None:
            try:
                sub = ydl.extract_info(e["url"], download=False)
            except Exception:
                continue
            if sub:
                _flatten(ydl, sub, out, limit, depth + 1, since_ts)


_LIST_TTL = 6 * 3600
_LIST_INCOMPLETE_TTL = 30 * 60  # growing playlists refetch sooner; a cached "5 videos" must not stick 6h


def _list_cache_path(urls, since):
    import hashlib
    key = hashlib.sha256(("\n".join(sorted(urls)) + "\n" + str(since or "")).encode()).hexdigest()[:16]
    return os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                        "tube2note", "lists", key + ".json")


def _list_load(urls, max_n, since):
    try:
        d = json.load(open(_list_cache_path(urls, since), encoding="utf-8"))
        if not isinstance(d, dict):
            return None
        age = time.time() - (d.get("ts", 0) or 0)
        ttl = _LIST_TTL if d.get("complete") else _LIST_INCOMPLETE_TTL
        if (age < ttl and isinstance(d.get("videos"), list)
                and (d.get("complete") or (d.get("max_n", 0) or 0) >= (max_n or 100))):
            return d["videos"][:max_n], d.get("hint")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return None


def _list_save(urls, max_n, since, videos, hint, complete):
    if not videos:  # never cache an empty listing: a failed list must retry, not stick for 6h
        return
    try:
        p = _list_cache_path(urls, since)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        json.dump({"ts": time.time(), "max_n": max_n, "complete": complete,
                   "videos": videos, "hint": hint},
                  open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, p)
    except (OSError, ValueError, TypeError):
        pass


def _channel_id(url, cookies_from_browser=None):
    """UC-id straight from /channel/ URLs; single cheap lookup otherwise. None if not a channel."""
    m = re.search(r"/channel/(UC[\w-]{22})(?![\w-])", url or "")
    if m:
        return m.group(1)
    if not re.search(r"youtube\.com/(@|c/|user/)|youtu\.be/", url or ""):
        return None
    try:
        opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "socket_timeout": 20}
        if cookies_from_browser:
            opts["cookiesfrombrowser"] = cookies_from_browser
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        cid = (info or {}).get("channel_id") or ""
        return cid if re.fullmatch(r"UC[\w-]{22}", cid) else None
    except Exception:
        return None


def _parse_rss_ts(s):
    """YouTube RSS published -> epoch. Handles Zulu, offsets, and bare forms."""
    s = (s or "").strip()
    if not s:
        return 0
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    except (ValueError, TypeError):
        return 0


def rss_videos(url, since_ts, max_n=100, opener=None, cookies_from_browser=None):
    """Fast path for --since on channels: official RSS feed, no full listing.
    Returns [videos] (possibly empty = nothing new) or None (not usable -> fall back)."""
    if not since_ts:
        return None
    cid = _channel_id(url, cookies_from_browser)
    if not cid:
        return None
    try:
        req = _make_req(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
        ctx = opener(req) if opener else urllib.request.urlopen(req, timeout=20)
        with ctx as r:
            raw = r.read()
        data = (raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw or ""))
        data = data.lstrip("﻿")
        if not data.strip():
            return None
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        root = ET.fromstring(data)
        title_el = root.find("a:title", ns)
        chan = title_el.text if title_el is not None else ""
        out = []
        for e in root.findall("a:entry", ns):
            vid = e.find("yt:videoId", ns)
            pub = e.find("a:published", ns)
            title = e.find("a:title", ns)
            if vid is None or pub is None:
                continue
            vid = (vid.text or "").strip()
            if not vid:
                continue
            ts = _parse_rss_ts(pub.text)
            if not ts or ts < since_ts:
                continue
            out.append({"id": vid, "title": (title.text if title is not None else vid) or vid,
                        "channel": chan or None,
                        "url": f"https://www.youtube.com/watch?v={vid}"})
            if len(out) >= (max_n or 100):
                break
        return out
    except Exception:
        return None


def expand(urls, max_n, since=None, fresh=False, cookies_from_browser=None):
    cached = None if fresh else _list_load(urls, max_n, since)
    if cached is not None:
        _say(f"list from cache ({len(cached[0])} videos)")
        return cached
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "socket_timeout": 20}
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = cookies_from_browser
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
    uniq = uniq[:max_n]
    if uniq:  # never cache an empty listing: a failed list must retry, not stick for 6h
        _list_save(urls, max_n, since, uniq, hint, len(out) < max_n)
    return uniq, hint


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


def sponsor_ranges(vid, cats=("sponsor",), opener=None):
    """SponsorBlock skip ranges [(start, end)]; fail-open [] on any error."""
    try:
        import urllib.parse
        q = urllib.parse.quote(json.dumps(list(cats)))
        req = _make_req(f"https://sponsor.ajay.app/api/skipSegments?videoID={vid}&categories={q}")
        ctx = opener(req) if opener else urllib.request.urlopen(req, timeout=10)
        with ctx as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        out = []
        for d in data or []:
            try:
                seg = d.get("segment") if isinstance(d, dict) else d
                out.append((float(seg[0]), float(seg[1])))
            except (TypeError, ValueError, IndexError, AttributeError):
                continue
        return out
    except Exception:
        return []


def strip_sponsored(segs, ranges):
    if not ranges:
        return segs
    return [(st, t) for st, t in (segs or [])
            if not any(s <= st < e for s, e in ranges)]


def fetch_vtt(formats, opener=None):
    """Try each format in order (vtt first). One dead mirror must not kill the video."""
    want = [f for f in (formats or []) if isinstance(f, dict) and f.get("url")] or []
    if not want and formats:
        want = [f for f in formats if isinstance(f, dict) and f.get("url")]
    want = [f for f in want if f.get("ext") == "vtt"] or want
    last = None
    for f in want:
        try:
            req = _make_req(f["url"])
            if opener is None:  # plain stdlib (tests, offline use)
                ctx = urllib.request.urlopen(req, timeout=20)
            else:  # yt-dlp handler: proxy, cookies, impersonation aware
                ctx = opener(req)
            with ctx as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
            continue
    raise last if last is not None else RuntimeError("no subtitle formats")


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
            if not info:
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
            cached = open(p, encoding="utf-8").read()
            if "-->" in cached:
                return cached, True
            os.unlink(p)  # poisoned cache (error page, not captions): refetch
        except (OSError, ValueError):
            pass
    if fetch_gap > 0:
        time.sleep(random.uniform(1, max(1, fetch_gap)))  # pace timedtext fetches only
    vtt = fetch_vtt(fmts, opener)
    if "-->" not in vtt:
        return vtt, False  # not captions: don't cache poison, caller skips the video
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(vtt)
        os.replace(tmp, p)
    except OSError:
        pass
    return vtt, False
