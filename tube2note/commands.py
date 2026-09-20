"""Small subcommands: doctor, widget, extras, status, dry-run."""
import json
import os
import shutil
import sys
import time
import urllib.request

from . import __version__
from .config import load_config, save_config
from .output import _count_lines
from .pdf import _has_fpdf
from .source import detect_langs, expand
from .ui import dim, panel, table
from .whisper import find_whisper


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
                'else exec python3 -m tube2note --resume-last; fi\n')
    os.chmod(dst, 0o755)
    print(f"Widget written to {dst} (needs Termux:Widget app).")


def _has_faster_whisper():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


EXTRAS = {
    "pdf": {"desc": "PDF export (fpdf2, ~5MB)",
            "size": "~5MB",
            "check": _has_fpdf,
            "pip": ["fpdf2"]},
    "whisper": {"desc": "Offline transcription via whisper.cpp binary + tiny model (~75MB)",
                "size": "~75MB model",
                "check": lambda: find_whisper()[0] is not None,
                "pip": []},
    "faster-whisper": {"desc": "Local neural STT (needs compiled torch/onnx — NOT installable on Termux, PC only)",
                "size": "~500MB",
                "check": _has_faster_whisper,
                "pip": ["faster-whisper"]},
}


def ensure_extra(name, auto_yes=False):
    """Make sure an extra is available: check, else ask consent and install. Returns True if ready."""
    info = EXTRAS.get(name)
    if info is None:
        print(f"unknown extra: {name}")
        return False
    try:
        if info["check"]():
            return True
    except Exception:
        pass
    print(f"This needs the '{name}' extra: {info['desc']} [{info['size']}].")
    if not auto_yes:
        try:
            ans = input("Download and enable it now? [y/N] > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False
        if ans not in ("y", "yes"):
            print("Skipped. Re-run with --yes to skip this prompt.")
            return False
    for pkg in info.get("pip", []):
        print(f"Installing {pkg}...")
        import subprocess
        r = subprocess.run([sys.executable, "-m", "pip", "install", pkg],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Install failed:\n{r.stderr[-500:]}")
            return False
    try:
        ok = bool(info["check"]())
    except Exception:
        ok = False
    if ok:
        try:
            store = load_config()
            store.setdefault("extras", {})[name] = True
            save_config(store)
        except OSError:
            pass
        return True
    print(f"'{name}' still not available after install. See README troubleshooting.")
    return False


def cmd_extras(argv=None):
    argv = argv or []
    if len(argv) >= 2 and argv[0] == "install":
        print("installed." if ensure_extra(argv[1], "--yes" in argv) else "not installed.")
        return
    if len(argv) >= 2 and argv[0] == "remove":
        name = argv[1]
        info = EXTRAS.get(name)
        if info is None:
            print(f"unknown extra: {name}")
            return
        import subprocess
        for pkg in info.get("pip", []):
            r = subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", pkg],
                               capture_output=True, text=True)
            print(r.stdout.strip().splitlines()[-1] if r.returncode == 0 else f"remove failed: {r.stderr[-200:]}")
        try:
            store = load_config()
            store.get("extras", {}).pop(name, None)
            save_config(store)
        except OSError:
            pass
        return
    rows = []
    for name, info in EXTRAS.items():
        try:
            ok = bool(info["check"]())
        except Exception:
            ok = False
        rows.append([name, info["desc"], "installed" if ok else "missing"])
    print(table(["Extra", "What", "Status"], rows))
    print(dim("Usage: extras [install|remove] <name> [--yes]"))


def _pkg_version():
    return __version__


def cmd_share():
    """Install a Termux share-sheet hook: share a YouTube link from any app into tube2note."""
    dst = os.path.expanduser("~/bin/termux-url-opener")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("#!/data/data/com.termux/files/usr/bin/bash\n"
                "# tube2note share hook: `Share > Termux` on a YouTube link downloads its transcript.\n"
                'cd "$HOME/yt2md" || exit 1\n'
                'if command -v tube2note >/dev/null; then exec tube2note -o shared.md "$1"; '
                'else exec python3 -m tube2note -o shared.md "$1"; fi\n')
    os.chmod(dst, 0o755)
    print(f"Share hook written to {dst} (Share a YouTube link > Termux).")


def cmd_status(d=".", as_json=False):
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
    if as_json:
        print(json.dumps([{"collection": r[0], "done": int(r[1]), "skipped": int(r[2]),
                           "size": r[3]} for r in rows], indent=2))
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
