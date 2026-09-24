"""Watch mode: re-check channels/playlists, collect only new videos."""
import glob
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


def _state_path(urls, out, outdir="", lang=""):
    parts = list(sorted(urls)) + [out]
    if outdir:
        parts.append(outdir)
    if lang:
        parts.append(lang)
    key = hashlib.sha256(("\n".join(parts)).encode()).hexdigest()[:16]
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
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seen": sorted(seen)}, f)
        os.replace(tmp, path)  # atomic: readers never see a half-written state
    except OSError:
        pass


def _new_videos(videos, seen):
    return [v for v in videos if v.get("id") not in seen]


def _cache_base():
    return os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))


def _pid_path(key=None, out=None):
    base = os.path.join(_cache_base(), "tube2note")
    if key is None and out is None:
        legacy = os.path.join(base, "watch.pid")  # legacy: no-arg callers / old daemons
        try:
            pers = sorted(glob.glob(os.path.join(base, "watch-*.pid")))
            if not os.path.exists(legacy) and len(pers) == 1:
                return pers[0]  # no-arg callers follow the single per-set daemon
        except OSError:
            pass
        return legacy
    h = hashlib.sha256(repr((key, out)).encode()).hexdigest()[:16]
    return os.path.join(base, f"watch-{h}.pid")


def _watch_key(targets, outdir=""):
    """Per-watch identity (hash of state paths): distinct subs/out sets get distinct pidfiles."""
    parts = []
    for sub, o, lang in targets:
        url = sub.get("url") if isinstance(sub, dict) else str(sub)
        try:
            parts.append(_state_path([url], o or "", outdir or "", lang or ""))
        except Exception:
            parts.append(f"{url}|{o}|{lang}|{outdir}")
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()[:16]


def _pid_candidates():
    cands = [_pid_path()]
    try:
        cands += sorted(glob.glob(os.path.join(os.path.dirname(cands[0]), "watch-*.pid")))
    except OSError:
        pass
    return list(dict.fromkeys(cands))


def _read_pidfile(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        if isinstance(d, dict):
            try:
                pid = int(str(d.get("pid")).strip())
            except (ValueError, TypeError, AttributeError):
                return {}
            d = dict(d)
            d["pid"] = pid
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
                          "clean": a.clean},
                         getattr(a, "profile", None) or os.environ.get("YT2MD_PROFILE") or None)
    outdir = os.path.abspath(os.path.expanduser(cfg["outdir"]))
    if outdir == os.path.abspath("."):
        return os.path.join(_cache_base(), "tube2note", "watch.log")
    return os.path.join(outdir, "watch.log")


def _daemonize(logpath, pidpath):
    if os.name == "nt" or not hasattr(os, "fork"):
        raise SystemExit("watch --daemon is not supported on Windows "
                         "(use --interval with Task Scheduler instead).")
    import select
    r, w = os.pipe()
    try:
        pid = os.fork()
    except OSError as e:
        os.close(r)
        os.close(w)
        raise SystemExit(f"watch: fork failed: {e}")
    if pid > 0:
        # parent: handshake before success (grandchild signals pidfile written)
        os.close(w)
        try:
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass
        me = b""
        try:
            if select.select([r], [], [], 10)[0]:
                me = os.read(r, 64)
        except OSError:
            me = b""
        finally:
            try:
                os.close(r)
            except OSError:
                pass
        if me.strip() and me.strip() != b"ERR":
            try:
                gpid = int(me.strip())
            except (ValueError, TypeError):
                gpid = -1
            print(f"watch: daemon started (pid {gpid}, log {logpath})", flush=True)
            raise SystemExit(0)
        print("watch: daemon failed to start (pidfile not written).", flush=True)
        raise SystemExit(1)
    os.setsid()
    try:
        pid2 = os.fork()
    except OSError as e:
        try:
            os.write(w, b"ERR")
        except OSError:
            pass
        raise SystemExit(f"watch: second fork failed: {e}")
    if pid2 > 0:
        # intermediate: exit quietly, original parent prints after handshake
        try:
            os.close(r)
        except OSError:
            pass
        try:
            os.close(w)
        except OSError:
            pass
        raise SystemExit(0)
    try:
        os.close(r)
    except OSError:
        pass
    os.umask(0o022)  # keep cwd: relative -o/-d/--subs/--cookies paths must keep working
    logf = open(logpath, "a", encoding="utf-8", buffering=1)
    os.dup2(open(os.devnull, "r").fileno(), 0)
    os.dup2(logf.fileno(), 1)
    os.dup2(logf.fileno(), 2)
    import tube2note.ui as _ui
    _ui.UI_ON = False
    _ui.set_verbose(False)
    me = os.getpid()
    if not _write_pidfile(pidpath, me):
        print("watch: PID file already exists (another daemon starting?) — exiting.", flush=True)
        try:
            os.write(w, b"ERR")
        except OSError:
            pass
        raise SystemExit(1)
    try:
        os.write(w, str(me).encode())
    except OSError:
        pass
    finally:
        try:
            os.close(w)
        except OSError:
            pass

    def _on_term(signum, frame):
        try:
            if _read_pidfile(pidpath).get("pid") == me:
                os.unlink(pidpath)
        except OSError:
            pass
        sys.exit(0)
    signal.signal(signal.SIGTERM, _on_term)


def _stop_one(path, quiet=False):
    data = _read_pidfile(path)
    pid = data.get("pid")
    if not pid:
        if not quiet:
            print("watch: not running (no PID file).")
        return 1
    if not _pid_is_alive(pid):
        if _read_pidfile(path).get("pid") == pid:
            _unlink_quiet(path)
        print(f"watch: stale PID file removed (pid {pid} dead).")
        return 1
    if not _is_ours(pid):
        if _read_pidfile(path).get("pid") == pid:
            _unlink_quiet(path)
        print(f"watch: stale PID file removed (pid {pid} reused by another process — NOT killed).")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        if _read_pidfile(path).get("pid") == pid:
            _unlink_quiet(path)
        print(f"watch: stale PID file removed (pid {pid} dead).")
        return 1
    for _ in range(50):
        time.sleep(0.1)
        if not _pid_is_alive(pid):
            break
    else:
        print(f"watch: pid {pid} ignoring SIGTERM; left running.")
        return 1
    if _read_pidfile(path).get("pid") == pid:
        _unlink_quiet(path)
    print(f"watch: stopped (pid {pid}).")
    return 0


def _cmd_stop():
    cands = [p for p in _pid_candidates() if os.path.exists(p)]
    if not any(_read_pidfile(p).get("pid") for p in cands):
        print("watch: not running (no PID file).")
        return 1
    any_ok = False
    any_fail = False
    for p in cands:
        if _read_pidfile(p).get("pid"):
            if _stop_one(p) == 0:
                any_ok = True
            else:
                any_fail = True
    return 0 if any_ok else (1 if any_fail else 1)  # 0 iff any daemon stopped


def _check(urls, out, cfg, args, since=None):
    """One check: list fresh, run new videos, update seen. Returns exit code."""
    path = _state_path(urls, out, cfg.get("outdir", ""), cfg.get("lang", ""))
    seen = _load_seen(path)
    try:
        if since:  # per-sub since; omitted when unset (keeps old expand mocks working)
            videos, _ = expand(urls, args.max, since=since, fresh=True)
        else:
            videos, _ = expand(urls, args.max, fresh=True)
    except Exception as e:
        print(f"watch: listing failed ({e}), will retry next round.")
        return 2
    if videos is None:
        print("watch: listing failed, will retry next round.")
        return 2
    if not videos:
        print("watch: no videos listed.")
        return 0
    fresh = _new_videos(videos, seen)
    if not fresh:
        print(f"watch: no new videos ({len(videos)} listed, all seen).")
        return 0
    print(f"watch: {len(fresh)} new video(s): " + ", ".join(
        (v.get("title") or v.get("id") or "?")[:50] for v in fresh[:5]))
    urls_to_get = [v.get("url") for v in fresh if v.get("url")]
    prof = getattr(args, "profile", None) or os.environ.get("YT2MD_PROFILE") or None
    res = (run_job(urls_to_get, out, cfg["lang"], len(fresh), args.sleep,
                   False, cfg["chunk"], cfg["chunk_cooldown_min"] * 60, args.throttle_cooldown,
                   videos=fresh, outdir=cfg["outdir"], ts=cfg["timestamps"] or args.timestamps,
                   verbose=args.verbose, layout=cfg["layout"], template=cfg["template"],
                   pdf=args.pdf, proxy=args.proxy, cookiefile=args.cookies, since=since,
                   clean=cfg["clean"], clean_level=cfg.get("clean_level", "full"),
                   link_timestamps=args.link_timestamps, srt=args.srt,
                   vtt=cfg.get("vtt", False) or getattr(args, "vtt", False),
                   txt=getattr(args, "txt", False),
                   transcribe=getattr(args, "transcribe", False),
                   summarize=getattr(args, "summarize", False),
                   diarize=cfg.get("diarize", False),
                   fast_subs=cfg.get("fast_subs", False),
                   whisper_model=cfg.get("whisper_model", "tiny"),
                   profile=prof) or {})
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
    ap.add_argument("--no-clean", dest="clean", action="store_false", default=None)
    ap.add_argument("--clean-level", default=None, help="cleaning strength: light or full")
    ap.add_argument("--diarize", dest="diarize", action="store_true", default=None)
    ap.add_argument("--no-diarize", dest="diarize", action="store_false")
    ap.add_argument("--fast-subs", dest="fast_subs", action="store_true", default=None,
                    help="subs-only: skip audio download/transcribe attempts")
    ap.add_argument("--no-fast-subs", dest="fast_subs", action="store_false")
    ap.add_argument("--vtt", dest="vtt", action="store_true", default=None)
    ap.add_argument("--no-vtt", dest="vtt", action="store_false")
    ap.add_argument("--txt", dest="txt", action="store_true", default=None)
    ap.add_argument("--no-txt", dest="txt", action="store_false")
    ap.add_argument("--transcribe", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--whisper-model", dest="whisper_model", default=None,
                    choices=["tiny", "base"])
    ap.add_argument("--profile", default=None, help="config profile name (or YT2MD_PROFILE)")
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
        subs = load_subs(os.path.expanduser(a.subs))
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
        prof = a.profile or os.environ.get("YT2MD_PROFILE") or None
        for sub, out, lang in targets:
            if not out:
                print(f"watch: entry {sub.get('url')} has no out, skipped.")
                code = code or 1
                continue
            cfg = resolve_config({"outdir": a.dir, "layout": a.layout, "lang": lang,
                                  "clean": a.clean, "clean_level": a.clean_level,
                                  "vtt": a.vtt, "diarize": a.diarize,
                                  "fast_subs": a.fast_subs,
                                  "whisper_model": a.whisper_model}, prof)
            code = _check([sub["url"]], out, cfg, a,
                          since=sub.get("since") if isinstance(sub, dict) else None) or code
        return code

    if a.daemon is not None:
        logpath = (_default_log_path(a) if a.daemon == "__default__"
                   else os.path.join(os.path.abspath(os.path.expanduser(a.daemon)), "watch.log"))
        try:
            os.makedirs(os.path.dirname(logpath), exist_ok=True)
        except OSError as e:
            ap.error(f"cannot write log dir: {e}")
        pidpath = _pid_path(_watch_key(targets, a.dir))
        data = _read_pidfile(pidpath)
        old = data.get("pid")
        if old and _pid_is_alive(old) and _is_ours(old):
            print(f"watch: already running (pid {old}).")
            return 1
        if old:
            _unlink_quiet(pidpath)
            print(f"watch: stale PID file removed (pid {old}).")
        elif os.path.exists(pidpath):
            _unlink_quiet(pidpath)
            print("watch: stale PID file removed (unreadable).")
        else:  # refuse if a legacy single-file daemon is still alive
            _legacy = os.path.join(_cache_base(), "tube2note", "watch.pid")
            lold = _read_pidfile(_legacy).get("pid")
            if lold and _pid_is_alive(lold) and _is_ours(lold):
                print(f"watch: already running (pid {lold}).")
                return 1
            if os.path.exists(_legacy):
                _unlink_quiet(_legacy)
                print("watch: stale PID file removed (legacy).")
        if a.verbose:
            print("watch: --verbose ignored in daemon mode (log uses quiet progress).", flush=True)
        a.verbose = False
        _daemonize(logpath, pidpath)
        print(f"watch: daemon running, interval {a.interval:g} min, log {logpath} "
              "(verbose off, dashboard off).", flush=True)

    code = _round()
    if a.interval and a.interval > 0:
        secs = a.interval * 60
        print(f"watch: next check in {a.interval:g} min (Ctrl+C to stop).")
        try:
            lag = 0.0  # last round duration: subtract so checks stay on cadence
            while True:
                time.sleep(max(0.0, secs - lag))
                t0 = time.monotonic()
                code = _round()
                lag = time.monotonic() - t0
                print(f"watch: next check in {a.interval:g} min (Ctrl+C to stop).")
        except KeyboardInterrupt:
            print("\nwatch: stopped.")
    return code
