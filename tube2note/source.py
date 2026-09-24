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
    if depth >= 3:  # channel -> tabs -> videos is 2 deep; deeper is cycles, never videos
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
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        if getattr(e, "errno", None) == 28:
            raise
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
    except (OSError, ValueError, TypeError) as e:
        if getattr(e, "errno", None) == 28:
            raise


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
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:  # bare form: device tz must not shift the epoch
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0


_RSS_CAP = 1 << 20  # feeds are KBs; never read unbounded


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
            raw = r.read(_RSS_CAP)
        data = (raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw or ""))
        data = data.lstrip("﻿")
        if not data.strip():
            return None
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        root = ET.fromstring(data)
        title_el = root.find("a:title", ns)
        chan = title_el.text if title_el is not None else ""
        out, seen = [], 0
        for e in root.findall("a:entry", ns):
            vid = e.find("yt:videoId", ns)
            pub = e.find("a:published", ns)
            title = e.find("a:title", ns)
            if vid is None or pub is None:
                continue
            vid = (vid.text or "").strip()
            if not vid:
                continue
            seen += 1
            ts = _parse_rss_ts(pub.text)
            if not ts or ts < since_ts:
                continue
            out.append({"id": vid, "title": (title.text if title is not None else vid) or vid,
                        "channel": chan or None,
                        "url": f"https://www.youtube.com/watch?v={vid}"})
            if len(out) >= (max_n or 100):
                break
        return out if seen else None  # [] = feed ok, nothing new; None = fail, fall back
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


def _open(req, opener, timeout):
    """Via the yt-dlp opener when present (proxy/cookies), else plain stdlib."""
    return opener(req) if opener is not None else urllib.request.urlopen(req, timeout=timeout)


_VTT_MAX = 5 * 1024 * 1024


def _read_capped(resp, cap=_VTT_MAX):
    return resp.read(cap + 1)[:cap + 1]


def _innertube_headers(req, extra):
    try:
        req.headers.update(extra)
    except Exception:
        try:
            for k, v in extra.items():
                req.add_header(k, v)
        except Exception:
            pass
    return req


def _xml_secs(el):
    if el.get("t") is not None:
        try:
            return float(el.get("t")) / 1000.0
        except (TypeError, ValueError):
            pass
    if el.get("start") is not None:
        try:
            return float(el.get("start"))
        except (TypeError, ValueError):
            pass
    b = (el.get("begin") or "").strip()
    if b:
        try:
            if b.endswith("s"):
                return float(b[:-1])
            p = b.split(":")
            if len(p) == 3:
                return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
            return int(p[0]) * 60 + float(p[1])
        except (ValueError, IndexError, AttributeError):
            pass
    return None


def _xml_segs(raw):
    import html as _h
    import xml.etree.ElementTree as ET
    root = ET.fromstring(raw)
    out = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag.rsplit("}", 1)[-1] not in ("p", "text"):
            continue
        st = _xml_secs(el)
        if st is None:
            continue
        tx = re.sub(r" {2,}", " ", _h.unescape("".join(el.itertext())).replace(" ", " ").strip())
        if tx:
            out.append((float(st), tx))
    return sorted(out)


def innertube_subs(vid, lang="en", opener=None):
    """Innertube ANDROID player -> captionTracks -> timedtext (vtt>srv3>ttml). [] on any error."""
    try:
        lang = (lang or "en").strip() or "en"
        if not re.fullmatch(r"[\w-]{11}", vid or ""):
            return []
        body = json.dumps({"videoId": vid, "context": {"client": {
            "clientName": "ANDROID", "clientVersion": "20.10.38", "hl": lang, "gl": "US"}}}).encode()
        url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
            "X-YouTube-Client-Name": "ANDROID",
            "X-YouTube-Client-Version": "20.10.38"})
        ctx = _open(req, opener, 20)
        with ctx as r:
            player = json.loads(_read_capped(r).decode("utf-8", errors="ignore"))
        tracks = (player.get("captions") or {}).get(
            "playerCaptionsTracklistRenderer", {}).get("captionTracks") or []
        tracks = [t for t in tracks if isinstance(t, dict) and t.get("baseUrl")]
        if not tracks:
            return []
        base_lg = lang.split("-")[0].split("_")[0]
        track = next((t for t in tracks if t.get("languageCode") == lang), None)
        if track is None:
            track = next((t for t in tracks
                          if (t.get("languageCode") or "").split("-")[0].split("_")[0] == base_lg), None)
        track = track or tracks[0]
        base = track["baseUrl"]
        from .vtt import vtt_segments
        for fmt in ("vtt", "srv3", "ttml"):
            try:
                u = re.sub(r"([?&])fmt=[^&]*", rf"\1fmt={fmt}", base) if "fmt=" in base \
                    else base + ("&" if "?" in base else "?") + f"fmt={fmt}"
                with _open(_make_req(u), opener, 20) as r2:
                    raw = _read_capped(r2).decode("utf-8", errors="ignore")
                if not raw or not raw.strip():
                    continue
                segs = vtt_segments(raw) if fmt == "vtt" else _xml_segs(raw)
                if segs:
                    return segs
            except Exception as e:
                if getattr(e, "errno", None) == 28:
                    raise
                continue
        return []
    except Exception as e:
        if getattr(e, "errno", None) == 28:
            raise
        return []


def sponsor_ranges(vid, cats=("sponsor",), opener=None):
    """SponsorBlock skip ranges [(start, end)]; fail-open [] on any error."""
    try:
        if not re.fullmatch(r"[\w-]{11}", vid or ""):
            return []
        import urllib.parse
        cats = [c.strip() for c in (cats or ("sponsor",)) if (c or "").strip()]
        q = urllib.parse.quote(",".join(cats or ["sponsor"]))
        req = _make_req(f"https://sponsor.ajay.app/api/skipSegments?videoID={vid}&categories={q}")
        with _open(req, opener, 10) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        out = []
        for d in data or []:
            try:
                seg = d.get("segment") if isinstance(d, dict) else d
                s, e = float(seg[0]), float(seg[1])
                if e <= s:
                    continue
                out.append((s, e))
            except (TypeError, ValueError, IndexError, AttributeError):
                continue
        return out
    except Exception as e:
        if getattr(e, "errno", None) == 28:
            raise
        return []


def strip_sponsored(segs, ranges):
    if not ranges:
        return segs
    return [(st, t) for st, t in (segs or [])
            if not any(s <= st < e for s, e in ranges)]


def fetch_vtt(formats, opener=None, bucket=None):
    """Try each format in order (vtt first). One dead mirror must not kill the video."""
    want = [f for f in (formats or []) if isinstance(f, dict) and f.get("url")] or []
    if not want and formats:
        want = [f for f in formats if isinstance(f, dict) and f.get("url")]
    want = [f for f in want if f.get("ext") == "vtt"] or want
    last = None
    for i, f in enumerate(want):
        try:
            if bucket is not None and i:  # pace mirrors, not the first try
                bucket.wait()
            with _open(_make_req(f["url"]), opener, 20) as r:
                return _read_capped(r).decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
            try:  # honor Retry-After before the next mirror
                from .throttle import _is_throttle, _retry_after_hint
                if _is_throttle(e):
                    time.sleep(_retry_after_hint(e, 2, cap=120))
            except Exception:
                pass
            continue
    raise last if last is not None else RuntimeError("no subtitle formats")


_PROBE_CAP = 5  # sampling more videos rarely changes the suggestion, always costs extract_info


def detect_langs(videos, probe=3, want=("tr", "en"), ydl_opts=None):
    """Sample the first few videos for ORIGINAL subtitle languages: (suggestion, found).
    tlang translations are ignored (most 429-prone kind)."""
    direct, anykey = {}, {}
    n = max(0, min(probe if probe else _PROBE_CAP, _PROBE_CAP))  # caller hint, capped
    opts = dict(ydl_opts) if ydl_opts else {"quiet": True, "no_warnings": True, "skip_download": True,
                                            "socket_timeout": 20}
    with YoutubeDL(opts) as ydl:
        for v in (videos or [])[:n]:
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


_VTT_CAP = 2 * 1024 * 1024  # giant payloads are error pages, never worth caching


def _get_vtt(vid, lg, auto, fmts, opener, fetch_gap=10):
    """Shared subtitle cache: same video is never downloaded twice (429-friendly).
    The key includes the track kind so a later manual upload replaces stale auto text."""
    from .vtt import vtt_segments as _segs
    p = _cache_path(vid, lg, auto)
    if os.path.exists(p):
        try:
            if os.path.getsize(p) > _VTT_CAP:
                os.unlink(p)  # huge: never a real transcript, refetch
            else:
                cached = open(p, encoding="utf-8").read()
                try:
                    ok = bool(_segs(cached))
                except Exception:
                    ok = "-->" in cached
                if ok:
                    return cached, True
                os.unlink(p)  # poisoned cache (error page, not captions): refetch
        except (OSError, ValueError) as e:
            if getattr(e, "errno", None) == 28:
                raise
    if fetch_gap > 0:
        time.sleep(random.uniform(1, max(1, fetch_gap)))  # pace timedtext fetches only
    vtt = fetch_vtt(fmts, opener)
    try:
        valid = bool(_segs(vtt))
    except Exception:
        valid = "-->" in (vtt or "")
    if not valid or len(vtt or "") > _VTT_CAP:
        return vtt, False  # not captions (or huge): don't cache poison, caller skips the video
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        open(tmp, "w", encoding="utf-8").write(vtt)
        os.replace(tmp, p)
    except OSError as e:
        if getattr(e, "errno", None) == 28:
            raise
    return vtt, False
