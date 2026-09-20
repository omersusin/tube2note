"""Listing channels/playlists via yt-dlp, subtitle picking and the shared subtitle cache."""
import datetime
import json
import os
import random
import sys
import time
import urllib.request

from yt_dlp import YoutubeDL


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


_LIST_TTL = 6 * 3600


def _list_cache_path(urls, since):
    import hashlib
    key = hashlib.sha256(("\n".join(sorted(urls)) + "\n" + str(since or "")).encode()).hexdigest()[:16]
    return os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                        "tube2note", "lists", key + ".json")


def _list_load(urls, max_n, since):
    try:
        d = json.load(open(_list_cache_path(urls, since), encoding="utf-8"))
        if (time.time() - d.get("ts", 0) < _LIST_TTL and isinstance(d.get("videos"), list)
                and (d.get("complete") or d.get("max_n", 0) >= max_n)):
            return d["videos"][:max_n], d.get("hint")
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def _list_save(urls, max_n, since, videos, hint, complete):
    if not videos:  # never cache an empty listing: a failed list must retry, not stick for 6h
        return
    try:
        p = _list_cache_path(urls, since)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump({"ts": time.time(), "max_n": max_n, "complete": complete,
                   "videos": videos, "hint": hint},
                  open(p, "w", encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass


def expand(urls, max_n, since=None, fresh=False):
    cached = None if fresh else _list_load(urls, max_n, since)
    if cached is not None:
        print(f"list from cache ({len(cached[0])} videos)", flush=True)
        return cached
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


def fetch_vtt(formats, opener=None):
    """Try each format in order (vtt first). One dead mirror must not kill the video."""
    want = [f for f in formats if f.get("ext") == "vtt"] or list(formats)
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
