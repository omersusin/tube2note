"""Watch mode: re-check channels/playlists, collect only new videos."""
import hashlib
import json
import os
import signal
import sys
import time

from .config import resolve_config
from .job import _exit_code, run_job
from .source import expand
from .subs import load_subs


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


def _cache_base():
    return os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))


def _pid_path():
    return os.path.join(_cache_base(), "tube2note", "watch.pid")


def _read_pidfile(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("pid"), int):
            return d
        return {"pid": int(str(d).strip())}  # legacy bare-int files
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _write_pidfile(path, pid):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "argv": sys.argv[:], "started": time.time()}, f)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def _unlink_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _pid_is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False


def _is_ours(pid):
    """PID-reuse guard: only SIGTERM processes that look like our watcher."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
        return "tube2note" in cmd and "watch" in cmd
    except (OSError, ValueError):
        return True  # no /proc (non-Linux): fall back to kill-0 + documented caveat


def _default_log_path(a):
    cfg = resolve_config({"outdir": a.dir, "layout": a.layout, "lang": a.lang,
                          "clean": a.clean}, None)
    outdir = os.path.abspath(os.path.expanduser(cfg["outdir"]))
    if outdir == os.path.abspath("."):
        return os.path.join(_cache_base(), "tube2note", "watch.log")
    return os.path.join(outdir, "watch.log")


def _daemonize(logpath, pidpath):
    if os.name == "nt" or not hasattr(os, "fork"):
        raise SystemExit("watch --daemon is not supported on Windows "
                         "(use --interval with Task Scheduler instead).")
    try:
        pid = os.fork()
    except OSError as e:
        raise SystemExit(f"watch: fork failed: {e}")
    if pid > 0:
        raise SystemExit(0)
    os.setsid()
    try:
        pid2 = os.fork()
    except OSError as e:
        raise SystemExit(f"watch: second fork failed: {e}")
    if pid2 > 0:
        print(f"watch: daemon started (pid {pid2}, log {logpath})", flush=True)
        raise SystemExit(0)
    os.umask(0o022)  # keep cwd: relative -o/-d/--subs/--cookies paths must keep working
    logf = open(logpath, "a", encoding="utf-8", buffering=1)
    os.dup2(open(os.devnull, "r").fileno(), 0)
    os.dup2(logf.fileno(), 1)
    os.dup2(logf.fileno(), 2)
    import tube2note.ui as _ui
    _ui.UI_ON = False
    _ui.set_verbose(False)
    me = os.getpid()
    _write_pidfile(pidpath, me)

    def _on_term(signum, frame):
        try:
            if _read_pidfile(pidpath).get("pid") == me:
                os.unlink(pidpath)
        except OSError:
            pass
        sys.exit(0)
    signal.signal(signal.SIGTERM, _on_term)


def _cmd_stop():
    p = _pid_path()
    data = _read_pidfile(p)
    pid = data.get("pid")
    if not pid:
        print("watch: not running (no PID file).")
        return 1
    if not _pid_is_alive(pid):
        _unlink_quiet(p)
        print(f"watch: stale PID file removed (pid {pid} dead).")
        return 1
    if not _is_ours(pid):
        _unlink_quiet(p)
        print(f"watch: stale PID file removed (pid {pid} reused by another process — NOT killed).")
        return 1
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        time.sleep(0.1)
        if not _pid_is_alive(pid):
            break
    else:
        print(f"watch: pid {pid} ignoring SIGTERM; left running.")
        return 1
    _unlink_quiet(p)
    print(f"watch: stopped (pid {pid}).")
    return 0


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
    res = (run_job([v["url"] for v in fresh], out, cfg["lang"], len(fresh), args.sleep,
                   False, cfg["chunk"], cfg["chunk_cooldown_min"] * 60, args.throttle_cooldown,
                   videos=fresh, outdir=cfg["outdir"], ts=cfg["timestamps"] or args.timestamps,
                   verbose=args.verbose, layout=cfg["layout"], template=cfg["template"],
                   pdf=args.pdf, proxy=args.proxy, cookiefile=args.cookies,
                   clean=cfg["clean"], clean_level=cfg["clean_level"],
                   link_timestamps=args.link_timestamps, srt=args.srt) or {})
    # save seen ONLY on a clean run: partial runs retry next round (.done makes it cheap)
    if res.get("total", 0) > 0 and res.get("skipped", 1) == 0:
        _save_seen(path, seen | {v.get("id") for v in videos if v.get("id")})
    elif res.get("ok", 0) > 0:
        print("watch: partial run, will retry skipped videos next round.")
    return _exit_code(res)


def cmd_watch(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="tube2note watch",
                                 description="Watch channels/playlists, collect new videos as they appear")
    ap.add_argument("urls", nargs="*", help="channel / playlist URLs to watch")
    ap.add_argument("--subs", default=None,
                    help="subscriptions.yaml file (url/out/lang per entry, no pyyaml needed)")
    ap.add_argument("-o", "--out", default="watch.md")
    ap.add_argument("--interval", type=float, default=0,
                    help="re-check every N minutes (0 = check once and exit, good for cron)")
    ap.add_argument("--daemon", nargs="?", const="__default__", default=None, metavar="LOGDIR",
                    help="detach into background (needs --interval N>0). Bare flag: watch.log "
                         "in outdir; with DIR: watch.log in DIR")
    ap.add_argument("--stop", action="store_true",
                    help="stop the running watch daemon (SIGTERM via PID file) and exit")
    ap.add_argument("--max", type=int, default=30, help="videos listed per check")
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--throttle-cooldown", type=int, default=1800)
    ap.add_argument("-d", "--dir", default=None)
    ap.add_argument("--layout", default=None)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--no-clean", dest="clean", action="store_false")
    ap.add_argument("--timestamps", action="store_true")
    ap.add_argument("--link-timestamps", action="store_true")
    ap.add_argument("--srt", action="store_true")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--cookies", default=None)
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    if a.stop and a.daemon is not None:
        ap.error("--stop and --daemon are mutually exclusive")
    if a.stop:
        return _cmd_stop()
    targets = [({"url": u}, a.out, a.lang) for u in a.urls]
    if a.subs:
        subs = load_subs(a.subs)
        if not subs:
            print(f"watch: no subscriptions in {a.subs}")
            return 1
        targets = [(s, s.get("out") or a.out, s.get("lang") or a.lang) for s in subs]
    if not targets:
        ap.error("give URLs or --subs subscriptions.yaml")
    if a.daemon is not None and not (a.interval and a.interval > 0):
        ap.error("--daemon needs --interval N>0 (minutes between checks)")

    def _round():
        code = 0
        for sub, out, lang in targets:
            if not out:
                print(f"watch: entry {sub.get('url')} has no out, skipped.")
                code = code or 1
                continue
            cfg = resolve_config({"outdir": a.dir, "layout": a.layout, "lang": lang,
                                  "clean": a.clean}, None)
            code = _check([sub["url"]], out, cfg, a) or code
        return code

    if a.daemon is not None:
        logpath = (_default_log_path(a) if a.daemon == "__default__"
                   else os.path.join(os.path.abspath(os.path.expanduser(a.daemon)), "watch.log"))
        try:
            os.makedirs(os.path.dirname(logpath), exist_ok=True)
        except OSError as e:
            ap.error(f"cannot write log dir: {e}")
        data = _read_pidfile(_pid_path())
        old = data.get("pid")
        if old and _pid_is_alive(old) and _is_ours(old):
            print(f"watch: already running (pid {old}).")
            return 1
        if old:
            _unlink_quiet(_pid_path())
            print(f"watch: stale PID file removed (pid {old}).")
        if a.verbose:
            print("watch: --verbose ignored in daemon mode (log uses quiet progress).", flush=True)
        a.verbose = False
        _daemonize(logpath, _pid_path())
        print(f"watch: daemon running, interval {a.interval:g} min, log {logpath} "
              "(verbose off, dashboard off).", flush=True)

    code = _round()
    if a.interval and a.interval > 0:
        secs = a.interval * 60
        print(f"watch: next check in {a.interval:g} min (Ctrl+C to stop).")
        try:
            while True:
                time.sleep(secs)
                code = _round()
                print(f"watch: next check in {a.interval:g} min (Ctrl+C to stop).")
        except KeyboardInterrupt:
            print("\nwatch: stopped.")
    return code
