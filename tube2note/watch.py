"""Watch mode: re-check channels/playlists, collect only new videos."""
import hashlib
import json
import os
import time

from .config import resolve_config
from .job import _exit_code, run_job
from .llm import _GEMINI_MODEL
from .source import expand


def _state_path(urls, out):
    key = hashlib.sha256(("\n".join(sorted(urls)) + "\n" + out).encode()).hexdigest()[:16]
    return os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                        "tube2note", "watch", key + ".json")


def _load_seen(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        if isinstance(d.get("seen"), list):
            return set(d["seen"])
    except (OSError, ValueError, AttributeError):
        pass
    return set()


def _save_seen(path, seen):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump({"seen": sorted(seen)}, open(path, "w", encoding="utf-8"))
    except OSError:
        pass


def _new_videos(videos, seen):
    return [v for v in videos if v.get("id") not in seen]


def _check(urls, out, cfg, args):
    """One check: list fresh, run new videos, update seen. Returns exit code."""
    path = _state_path(urls, out)
    seen = _load_seen(path)
    videos, _ = expand(urls, args.max, fresh=True)
    if not videos:
        print("watch: listing failed, will retry next round.")
        return 2
    fresh = _new_videos(videos, seen)
    if not fresh:
        print(f"watch: no new videos ({len(videos)} listed, all seen).")
        return 0
    print(f"watch: {len(fresh)} new video(s): " + ", ".join(v.get("title", v["id"])[:50] for v in fresh[:5]))
    res = run_job([v["url"] for v in fresh], out, cfg["lang"], len(fresh), args.sleep,
                  False, cfg["chunk"], cfg["chunk_cooldown_min"] * 60, args.throttle_cooldown,
                  videos=fresh, outdir=cfg["outdir"], ts=cfg["timestamps"],
                  verbose=args.verbose, layout=cfg["layout"], template=cfg["template"],
                  pdf=args.pdf, proxy=args.proxy, cookiefile=args.cookies,
                  clean=cfg["clean"], clean_level=cfg["clean_level"])
    if (res or {}).get("total", 0) > 0:  # empty result = fatal (throttled out): retry next round
        _save_seen(path, seen | {v.get("id") for v in videos if v.get("id")})
    return _exit_code(res)


def cmd_watch(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="tube2note watch",
                                 description="Watch channels/playlists, collect new videos as they appear")
    ap.add_argument("urls", nargs="+", help="channel / playlist URLs to watch")
    ap.add_argument("-o", "--out", default="watch.md")
    ap.add_argument("--interval", type=float, default=0,
                    help="re-check every N minutes (0 = check once and exit, good for cron)")
    ap.add_argument("--max", type=int, default=30, help="videos listed per check")
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--throttle-cooldown", type=int, default=1800)
    ap.add_argument("-d", "--dir", default=None)
    ap.add_argument("--layout", default=None)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--no-clean", dest="clean", action="store_false")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--cookies", default=None)
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    cfg = resolve_config({"outdir": a.dir, "layout": a.layout, "lang": a.lang,
                          "clean": a.clean}, None)
    code = _check(a.urls, a.out, cfg, a)
    if a.interval and a.interval > 0:
        secs = a.interval * 60
        print(f"watch: next check in {a.interval:g} min (Ctrl+C to stop).")
        try:
            while True:
                time.sleep(secs)
                code = _check(a.urls, a.out, cfg, a)
                print(f"watch: next check in {a.interval:g} min (Ctrl+C to stop).")
        except KeyboardInterrupt:
            print("\nwatch: stopped.")
    return code
