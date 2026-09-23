"""Local web UI: `tube2note serve`.

Stdlib only (no Flask/uvicorn/pydantic), so it installs anywhere Python does, Termux included.
The page runs each job as a normal `python -m tube2note ...` subprocess, so the CLI stays the single
source of truth: resume, layouts, throttling and Gemini options all behave exactly as on the command line.

Security model (this server can start downloads and write files, so it is not an open door):
  * binds to 127.0.0.1 by default; `--host 0.0.0.0` is opt-in and prints a warning
  * a random per-launch token (URL `?t=...`, then an HttpOnly SameSite=Strict cookie) is required for everything
  * Host header allow-list (blocks DNS rebinding), Origin check and JSON-only POSTs (blocks CSRF)
  * request fields are whitelisted and validated; the output folder is fixed at launch; URLs are passed after `--`
    so they can never be read as options; downloads are limited to .md/.pdf files inside that folder
"""
import argparse
import collections
import http.server
import json
import os
import re
import secrets
import shutil
import signal
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

from . import __version__
from .config import resolve_config
from .naming import sanitize_filename
from .output import _count_lines
from .pdf import _has_fpdf

URL_RE = re.compile(r"^https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/\S+$", re.IGNORECASE)
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?(,[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?){0,5}$")
SINCE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TARGET_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
PROGRESS_RE = re.compile(r"(\d+)/(\d+) videos · (\d+) words")
CURRENT_RE = re.compile(r"^\[(\d+)/(\d+)\] (.*)$")
LAYOUTS = ("single", "videos", "tree")
MAX_BODY = 64 * 1024
SERVED_EXT = {".md": "text/markdown", ".pdf": "application/pdf", ".epub": "application/epub+zip"}


def gemini_available():
    return bool(os.environ.get("GEMINI_API_KEY"))


# --------------------------------------------------------------------------- request -> argv

def _bool(v):
    if v is True or v == 1:
        return True
    return str(v or "").strip().lower() in ("1", "true", "on", "yes", "y")


def _int(v, lo, hi, default, label):
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if not lo <= n <= hi:
        raise ValueError(f"{label} must be between {lo} and {hi}")
    return n


def build_argv(p, base_dir, python=None):
    """Validate a JSON payload and turn it into a tube2note argv. Raises ValueError with a user-facing message."""
    if not isinstance(p, dict):
        raise ValueError("bad request")
    urls = p.get("urls") or []
    if isinstance(urls, str):
        urls = urls.split()
    urls = [str(u).strip() for u in urls if str(u).strip()]
    if not urls:
        raise ValueError("Paste at least one YouTube URL")
    if len(urls) > 50:
        raise ValueError("At most 50 URLs per job (a channel or playlist URL can hold hundreds of videos)")
    for u in urls:
        if not URL_RE.match(u):
            raise ValueError(f"Not a YouTube URL: {u[:60]}")
    raw_name = str(p.get("name") or "").strip()
    if not raw_name:  # auto: name it after the video/channel like the TUI does
        try:
            from .naming import slug
            from .source import expand as _expand
            _vids, _hint = _expand(urls, 5)
            raw_name = slug(_hint or (_vids[0].get("title") if _vids else "") or "tube2note")
        except Exception:
            raw_name = "tube2note"
    name = sanitize_filename(raw_name) or "tube2note"
    if not name.lower().endswith(".md"):
        name += ".md"
    layout = p.get("layout") or "single"
    if layout not in LAYOUTS:
        raise ValueError("Unknown layout")
    argv = list(python) if python else ([sys.executable] if getattr(sys, "frozen", False)
                                         else [sys.executable, "-m", "tube2note"])
    argv += ["--verbose", "-d", base_dir, "-o", name, "--layout", layout,
             "--max", str(_int(p.get("max"), 1, 5000, 100, "Max videos"))]
    lang = str(p.get("lang") or "").strip()
    if lang:
        if not LANG_RE.match(lang):
            raise ValueError("Language must look like: en or tr,en")
        argv += ["--lang", lang]
    since = str(p.get("since") or "").strip()
    if since:
        if not SINCE_RE.match(since):
            raise ValueError("Since must be YYYY-MM-DD")
        argv += ["--since", since]
    if _bool(p.get("timestamps")):
        argv.append("--timestamps")
    if _bool(p.get("link_timestamps")):
        argv.append("--link-timestamps")
    if _bool(p.get("srt")):
        argv.append("--srt")
    if p.get("clean") is not None and not _bool(p.get("clean")):
        argv.append("--no-clean")
    split = _int(p.get("split_words"), 0, 500000, 0, "Split words")
    if split:
        argv += ["--split-words", str(split)]
    workers = _int(p.get("workers"), 1, 4, 1, "Workers")
    if workers > 1:
        argv += ["--workers", str(workers)]
    if _bool(p.get("pdf")):
        argv.append("--pdf")
    if _bool(p.get("epub")):
        argv.append("--epub")
    if _bool(p.get("dry_run")):
        argv.append("--dry-run")
    if gemini_available():  # the key stays in the server's environment; the page never sees or sends it
        if _bool(p.get("transcribe")):
            argv.append("--transcribe")
        if _bool(p.get("summarize")):
            argv.append("--summarize")
        target = str(p.get("translate") or "").strip()
        bil = str(p.get("bilingual") or "").strip()
        if target and bil:
            raise ValueError("Translate and bilingual are mutually exclusive")
        for label, val in (("Translate", target), ("Bilingual", bil)):
            if val:
                if not TARGET_RE.match(val):
                    raise ValueError(f"{label} target must be a language code like tr")
                argv += ["--translate", val] if label == "Translate" else ["--bilingual", val]
    argv.append("--")
    argv += urls
    return argv


# --------------------------------------------------------------------------- job runner

class Job:
    """One tube2note subprocess plus a rolling log and parsed progress."""

    def __init__(self, argv, name, dry_run=False):
        self.argv, self.name, self.dry_run = argv, name, dry_run
        self._timer = None
        self.lines = collections.deque(maxlen=400)
        self.lock = threading.Lock()
        self.progress = {"done": 0, "total": 0, "words": 0}
        self.current = ""
        self.stopped = False
        self.started = time.time()
        self.ended = None
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", NO_COLOR="1")
        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, env=env, text=True, encoding="utf-8",
                                     errors="replace", bufsize=1)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                m, c = PROGRESS_RE.search(line), CURRENT_RE.match(line)
                with self.lock:
                    self.lines.append(line)
                    if m:
                        self.progress = {"done": int(m.group(1)), "total": int(m.group(2)), "words": int(m.group(3))}
                    if c:
                        self.current = c.group(3)[:120]
            self.proc.wait()
        finally:
            try:
                if self.proc.stdout:
                    self.proc.stdout.close()
            except Exception:
                pass
            if self._timer is not None:
                self._timer.cancel()
            self.ended = time.time()

    @property
    def running(self):
        return self.proc.poll() is None or self.ended is None

    def stop(self):
        if self.proc.poll() is not None:
            return
        self.stopped = True
        try:  # SIGINT lets the job flush its .done log like Ctrl+C would; fall back to terminate
            if self._timer is not None:
                self._timer.cancel()
            if os.name == "posix":
                self.proc.send_signal(signal.SIGINT)
                self._timer = threading.Timer(8, self._terminate)
                self._timer.daemon = True
                self._timer.start()
            else:
                self.proc.terminate()
        except OSError:
            pass

    def _terminate(self):
        if self.proc.poll() is None:
            self.proc.terminate()

    def snapshot(self, tail=250):
        with self.lock:
            lines = list(self.lines)[-tail:]
            progress, current = dict(self.progress), self.current
        rc = self.proc.poll()
        if self.running:
            state = "stopping" if self.stopped else "running"
        elif self.stopped:
            state = "stopped"
        else:
            state = "done" if rc in (0, 1) else "failed"  # 1 = partial success (some videos skipped)
        return {"state": state, "name": self.name, "dry_run": self.dry_run, "progress": progress,
                "current": current, "log": lines, "returncode": rc,
                "elapsed": int((self.ended or time.time()) - self.started)}


# --------------------------------------------------------------------------- files

def list_files(base_dir, limit=300):
    """.md/.pdf files under base_dir (depth <= 4), newest first, with resume counters for top-level collections."""
    out = []
    base_dir = os.path.realpath(base_dir)
    for root, dirs, files in os.walk(base_dir):
        depth = root[len(base_dir):].count(os.sep)
        dirs[:] = [d for d in dirs if not d.startswith(".")] if depth < 4 else []
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in SERVED_EXT or f.startswith("."):
                continue
            full = os.path.join(root, f)
            if os.path.islink(full):
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            item = {"path": os.path.relpath(full, base_dir).replace(os.sep, "/"), "size": st.st_size,
                    "mtime": int(st.st_mtime)}
            if root == base_dir and ext == ".md":
                if os.path.exists(full + ".db"):  # SQLite resume store (v0.12+)
                    try:
                        from .store import Store
                        _st = Store(full + ".db")
                        item["done"], item["skipped"] = _st.counts()
                        _st.close()
                    except Exception:
                        item["done"] = item["skipped"] = 0
                else:  # legacy sidecars
                    item["done"] = _count_lines(full + ".done")
                    item["skipped"] = _count_lines(full + ".skip")
            out.append(item)
    out.sort(key=lambda i: -i["mtime"])
    return out[:limit]


def resolve_served(base_dir, rel):
    """Map a URL path to a real file inside base_dir, or None. Blocks traversal, symlink escapes and odd types."""
    if not rel or "\x00" in rel or rel.startswith(("/", "\\")):
        return None
    parts = re.split(r"[\\/]", rel)
    if any(p in ("", ".", "..") for p in parts):
        return None
    base = os.path.realpath(base_dir)
    full = os.path.realpath(os.path.join(base, *parts))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in SERVED_EXT:
        return None
    return full


# --------------------------------------------------------------------------- HTTP

class App:
    def __init__(self, base_dir, token, host, port, argv_builder=build_argv, defaults=None,
                 public=False, allow_hosts=()):
        self.base_dir = os.path.abspath(base_dir)
        self.token, self.host, self.port = token, host, port
        self.public = public
        self.extra_hosts = set(allow_hosts)
        self.argv_builder = argv_builder
        self.defaults = defaults or {}
        self.job = None
        self.lock = threading.Lock()

    def allowed_hosts(self):
        names = {"127.0.0.1", "localhost", "[::1]"}
        if self.host not in ("0.0.0.0", "::", ""):
            names.add(self.host)
        names |= set(self.extra_hosts)
        return names

    def host_ok(self, host):
        host = (host or "").split(":")[0].lower()
        if host in self.allowed_hosts():
            return True
        return any(host.endswith(s) for s in self.extra_hosts if s.startswith("."))

    def any_host(self):
        return self.host in ("0.0.0.0", "::", "")

    def state(self):
        with self.lock:
            job = self.job.snapshot() if self.job else None
        return {"version": __version__, "base_dir": self.base_dir,
                "gemini": gemini_available() and not self.public,
                "pdf": _has_fpdf(), "defaults": self.defaults, "job": job,
                "running": bool(job and job["state"] in ("running", "stopping")),
                "files": list_files(self.base_dir)}

    def start(self, payload):
        if self.public and isinstance(payload, dict):
            # anonymous visitors must never spend the host's Gemini quota
            payload = {k: v for k, v in payload.items()
                       if k not in ("transcribe", "summarize", "translate", "bilingual")}
        argv = self.argv_builder(payload, self.base_dir)
        with self.lock:
            if self.job and self.job.running:
                raise RuntimeError("A job is already running")
            os.makedirs(self.base_dir, exist_ok=True)
            name = argv[argv.index("-o") + 1] if "-o" in argv else ""
            self.job = Job(argv, name, dry_run="--dry-run" in argv)

    def stop(self):
        with self.lock:
            if self.job:
                self.job.stop()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "tube2note"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the terminal for job messages
        pass

    @property
    def app(self):
        return self.server.app

    # -- helpers
    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def _err(self, code, msg):
        self._json(code, {"error": msg})

    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip()
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return self.app.any_host() or self.app.host_ok(name)

    def _cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "t2n":
                return v
        return ""

    def _authed(self):
        if getattr(self.app, "public", False):
            return True
        return secrets.compare_digest(self._cookie_token().encode(), self.app.token.encode())

    # -- routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._err(403, "bad host")
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            tok = (q.get("t") or [""])[0]
            if tok and secrets.compare_digest(tok.encode(), self.app.token.encode()):
                return self._send(302, b"", "text/plain", {
                    "Location": "/", "Set-Cookie": f"t2n={self.app.token}; Path=/; HttpOnly; SameSite=Strict"})
            if not self._authed():
                return self._send(401, "Open the link printed by `tube2note serve` (it contains the access token).",
                                  "text/plain; charset=utf-8")
            nonce = secrets.token_urlsafe(12)
            page = INDEX_HTML.replace("__NONCE__", nonce)
            csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                   "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            return self._send(200, page, "text/html; charset=utf-8", {"Content-Security-Policy": csp})
        if not self._authed():
            return self._err(401, "unauthorized")
        if url.path == "/api/state":
            return self._json(200, self.app.state())
        if url.path.startswith("/files/"):
            rel = urllib.parse.unquote(url.path[len("/files/"):])
            full = resolve_served(self.app.base_dir, rel)
            if not full:
                return self._err(404, "not found")
            with open(full, "rb") as f:
                data = f.read()
            ctype = SERVED_EXT[os.path.splitext(full)[1].lower()]
            if "view" in q and ctype == "text/markdown":
                return self._send(200, data, "text/plain; charset=utf-8")
            fname = urllib.parse.quote(os.path.basename(full))
            return self._send(200, data, ctype + ("; charset=utf-8" if ctype.startswith("text") else ""),
                              {"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})
        return self._err(404, "not found")

    def do_POST(self):
        if not self._host_ok():
            return self._err(403, "bad host")
        if not self._authed():
            return self._err(401, "unauthorized")
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host"):
            return self._err(403, "cross-origin request refused")
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            return self._err(415, "JSON only")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= MAX_BODY:
            return self._err(413, "body too large")
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._err(400, "invalid JSON")
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/start":
            try:
                self.app.start(payload)
            except ValueError as e:
                return self._err(400, str(e))
            except RuntimeError as e:
                return self._err(409, str(e))
            return self._json(200, self.app.state())
        if path == "/api/stop":
            self.app.stop()
            return self._json(200, self.app.state())
        return self._err(404, "not found")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(base_dir, host="127.0.0.1", port=8765, token=None, argv_builder=build_argv, defaults=None,
                public=False, allow_hosts=()):
    token = token or secrets.token_urlsafe(18)
    last = None
    for p in ([port] if port == 0 else range(port, port + 10)):
        try:
            srv = Server((host, p), Handler)
            break
        except OSError as e:
            last = e
    else:
        raise last
    srv.app = App(base_dir, token, host, srv.server_address[1], argv_builder, defaults,
                  public=public, allow_hosts=allow_hosts)
    return srv


def _open_browser(url):
    if os.environ.get("TERMUX_VERSION") or shutil.which("termux-open-url"):
        exe = shutil.which("termux-open-url")
        if exe:
            subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def cmd_serve(argv):
    ap = argparse.ArgumentParser(prog="tube2note serve", description="Local web UI for tube2note")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1; 0.0.0.0 exposes it to your network)")
    ap.add_argument("-d", "--dir", default=None, help="output folder (default: your configured folder, or ./tube2note-out)")
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    ap.add_argument("--token", default=None, help="fixed access token (default: random per launch)")
    ap.add_argument("--public", action="store_true", help="no token required (only for public demos you trust)")
    ap.add_argument("--allow-host", action="append", default=[], help="extra Host header to accept (tunnel domains)")
    a = ap.parse_args(argv)
    cfg = resolve_config()
    base = os.path.expanduser(a.dir or (cfg["outdir"] if cfg["outdir"] != "." else "tube2note-out"))
    defaults = {"lang": cfg.get("lang") or "", "layout": cfg.get("layout") or "single",
                "timestamps": bool(cfg.get("timestamps")), "clean": cfg.get("clean") is not False}
    srv = make_server(base, a.host, a.port, a.token, defaults=defaults, public=a.public,
                      allow_hosts=a.allow_host)
    shown = "127.0.0.1" if a.host in ("0.0.0.0", "::", "") else a.host
    url = f"http://{shown}:{srv.app.port}/?t={srv.app.token}"
    print(f"tube2note web UI  ->  {url}")
    print(f"output folder: {srv.app.base_dir}")
    if a.host in ("0.0.0.0", "::", ""):
        print("WARNING: listening on all interfaces. Anyone on your network who has the token link can start jobs. "
              "Use only on a network you trust.")
    print("Ctrl+C to stop.")
    if not a.no_open:
        _open_browser(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        srv.app.stop()
        srv.server_close()


# --------------------------------------------------------------------------- page

INDEX_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>tube2note</title>
<style nonce="__NONCE__">
:root{--bg:#f6f7f9;--card:#fff;--fg:#14181f;--mut:#667085;--line:#e3e6ec;--acc:#d92d20;--acc2:#b42318;--ok:#067647;--warn:#b54708;--bad:#b42318;--code:#0f1420;--codefg:#d6deeb}
@media(prefers-color-scheme:dark){:root{--bg:#0d1017;--card:#161b26;--fg:#e8ecf3;--mut:#98a2b3;--line:#262d3c;--acc:#f04438;--acc2:#d92d20;--ok:#47cd89;--warn:#fdb022;--bad:#f97066}}
[hidden]{display:none!important}*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:12px 12px calc(96px + env(safe-area-inset-bottom))}
main{max-width:720px;margin:0 auto}
h1{font-size:20px;margin:6px 2px 2px}h1 small{font-weight:400;color:var(--mut);font-size:13px}
.sub{color:var(--mut);font-size:13px;margin:0 2px 12px;word-break:break-all}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:0 0 12px}
.card h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:0 0 10px}
label{display:block;font-size:13px;color:var(--mut);margin:10px 0 4px}
textarea,input[type=text],input[type=number],input[type=date],select{width:100%;font:inherit;color:inherit;background:transparent;border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-height:44px}
textarea{min-height:110px;resize:vertical}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.chk{display:flex;align-items:center;gap:10px;min-height:44px;font-size:16px;color:var(--fg);margin:0}
.chk input{width:22px;height:22px;accent-color:var(--acc)}
details{margin-top:8px}summary{cursor:pointer;color:var(--mut);min-height:44px;display:flex;align-items:center}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 12px calc(10px + env(safe-area-inset-bottom));display:flex;gap:10px;justify-content:center}
.bar .in{display:flex;gap:10px;width:100%;max-width:720px}
button{font:inherit;font-weight:600;border:0;border-radius:12px;min-height:48px;padding:0 18px;cursor:pointer}
.go{flex:1;background:var(--acc);color:#fff}.go:active{background:var(--acc2)}
.sec{background:transparent;color:var(--fg);border:1px solid var(--line)}
.stop{flex:1;background:var(--bad);color:#fff}
button:disabled{opacity:.45}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.pill.running,.pill.stopping{color:var(--warn)}.pill.done{color:var(--ok)}.pill.failed,.pill.stopped{color:var(--bad)}
.meter{height:10px;background:var(--line);border-radius:99px;overflow:hidden;margin:10px 0 6px}.meter i{display:block;height:100%;background:var(--acc);width:0;transition:width .4s}
.stat{color:var(--mut);font-size:13px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
pre{background:var(--code);color:var(--codefg);border-radius:10px;padding:10px;margin:10px 0 0;max-height:260px;overflow:auto;font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.err{color:var(--bad);font-size:14px;margin:8px 2px 0;min-height:1em}
.file{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 0;border-top:1px solid var(--line)}
.file:first-of-type{border-top:0}.file b{font-weight:600;word-break:break-all}.file small{display:block;color:var(--mut)}
.file a{color:var(--acc);text-decoration:none;font-weight:600;padding:10px 6px;white-space:nowrap}
.hint{color:var(--mut);font-size:13px;margin:8px 2px}
</style></head><body><main>
<h1>tube2note <small id="ver"></small></h1>
<p class="sub" id="dir"></p>

<section class="card"><h2>New job</h2>
<label for="urls">YouTube URLs (one per line: channel, playlist or videos)</label>
<textarea id="urls" placeholder="https://www.youtube.com/@SomeChannel/videos" autocapitalize="off" spellcheck="false"></textarea>
<div class="row">
<div><label for="name">Output name (empty = video title)</label><input type="text" id="name" value="" placeholder="auto (video title)" autocapitalize="off"></div>
<div><label for="lang">Languages</label><input type="text" id="lang" placeholder="en or tr,en" autocapitalize="off"></div>
</div>
<label class="chk"><input type="checkbox" id="timestamps"> Keep [MM:SS] timestamps</label>
<label class="chk"><input type="checkbox" id="link_timestamps"> Clickable timestamp links</label>
<label class="chk"><input type="checkbox" id="srt"> Write .srt sidecars</label>
<label class="chk"><input type="checkbox" id="clean" checked> Clean transcripts</label>
<label class="chk" id="pdfrow"><input type="checkbox" id="pdf"> Also write PDF</label>
<label class="chk"><input type="checkbox" id="epub"> Also write EPUB</label>
<details><summary>More options</summary>
<div class="row">
<div><label for="layout">Layout</label><select id="layout"><option>single</option><option>videos</option><option>tree</option></select></div>
<div><label for="max">Max videos</label><input type="number" id="max" value="100" min="1" max="5000" inputmode="numeric"></div>
<div><label for="since">Since (date)</label><input type="date" id="since"></div>
<div><label for="split_words">Split every N words</label><input type="number" id="split_words" value="0" min="0" inputmode="numeric"></div>
<div><label for="workers">Parallel workers (1 = safest)</label><input type="number" id="workers" value="1" min="1" max="4" inputmode="numeric"></div>
</div></details>
<div id="gem" hidden><details open><summary>Gemini (uses GEMINI_API_KEY from the server)</summary>
<label class="chk"><input type="checkbox" id="summarize"> Summarize each video</label>
<label class="chk"><input type="checkbox" id="transcribe"> Transcribe videos without captions</label>
<label for="translate">Translate to (language code, optional)</label><input type="text" id="translate" placeholder="tr" autocapitalize="off">
</details></div>
<p class="hint">Re-using the same output name resumes where it stopped.</p>
<p class="err" id="err" role="alert"></p>
</section>

<section class="card" id="jobcard" hidden><h2>Progress <span class="pill" id="pill"></span></h2>
<div class="stat"><span id="cur"></span><span id="nums"></span></div>
<div class="meter"><i id="meter"></i></div>
<pre id="log"></pre></section>

<section class="card"><h2>Files</h2><div id="files"><p class="hint">Nothing here yet.</p></div></section>
</main>
<div class="bar"><div class="in">
<button class="sec" id="preview">Preview</button>
<button class="go" id="start">Start</button>
<button class="stop" id="stop" hidden>Stop</button>
</div></div>
<script nonce="__NONCE__">
const $=id=>document.getElementById(id);
const FIELDS=["urls","name","lang","layout","max","since","split_words","workers","translate"];
const BOOLS=["timestamps","link_timestamps","srt","clean","pdf","epub","summarize","transcribe"];
let busy=false,timer=null,seeded=false;
function save(){try{const o={};FIELDS.forEach(f=>o[f]=$(f).value);BOOLS.forEach(f=>o[f]=$(f).checked);localStorage.setItem("t2n",JSON.stringify(o))}catch(e){}}
function load(){try{const o=JSON.parse(localStorage.getItem("t2n")||"null");if(!o)return false;FIELDS.forEach(f=>{if(o[f]!=null)$(f).value=o[f]});BOOLS.forEach(f=>{if(o[f]!=null)$(f).checked=o[f]});return true}catch(e){return false}}
function payload(dry){const p={dry_run:dry};FIELDS.forEach(f=>p[f]=$(f).value);BOOLS.forEach(f=>p[f]=$(f).checked);p.urls=$("urls").value.split(/\s+/).filter(Boolean);return p}
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});let j={};try{j=await r.json()}catch(e){}if(!r.ok)throw new Error(j.error||("HTTP "+r.status));return j}
function fmtSize(n){return n>1048576?(n/1048576).toFixed(1)+" MB":Math.max(1,Math.round(n/1024))+" KB"}
function fmtTime(s){return Math.floor(s/60)+"m "+String(s%60).padStart(2,"0")+"s"}
function render(s){
  $("ver").textContent="v"+s.version;$("dir").textContent=s.base_dir;
  $("gem").hidden=!s.gemini;$("pdfrow").hidden=!s.pdf;
  if(!seeded){seeded=true;if(!load()){const d=s.defaults||{};if(d.lang)$("lang").value=d.lang;if(d.layout)$("layout").value=d.layout;$("timestamps").checked=!!d.timestamps;$("clean").checked=d.clean!==false}}
  busy=s.running;$("start").hidden=$("preview").hidden=busy;$("stop").hidden=!busy;
  const j=s.job;$("jobcard").hidden=!j;
  if(j){const pill=$("pill");pill.textContent=j.state;pill.className="pill "+j.state;
    const p=j.progress,pct=p.total?Math.round(100*p.done/p.total):(j.state==="done"?100:0);
    $("meter").style.width=pct+"%";$("cur").textContent=j.current||j.name||"";
    $("nums").textContent=(p.total?p.done+"/"+p.total+" videos · "+p.words.toLocaleString()+" words · ":"")+fmtTime(j.elapsed);
    const log=$("log"),atEnd=log.scrollTop+log.clientHeight>=log.scrollHeight-24;log.textContent=j.log.join("\n");if(atEnd)log.scrollTop=log.scrollHeight}
  const box=$("files");box.textContent="";
  if(!s.files.length){const h=document.createElement("p");h.className="hint";h.textContent="Nothing here yet.";box.appendChild(h)}
  s.files.forEach(f=>{const row=document.createElement("div");row.className="file";
    const left=document.createElement("div"),b=document.createElement("b"),sm=document.createElement("small");
    b.textContent=f.path;sm.textContent=fmtSize(f.size)+(f.done!=null?" · "+f.done+" done"+(f.skipped?", "+f.skipped+" skipped":""):"");
    left.append(b,sm);const right=document.createElement("div"),href="/files/"+f.path.split("/").map(encodeURIComponent).join("/");
    if(f.path.endsWith(".md")){const v=document.createElement("a");v.href=href+"?view=1";v.target="_blank";v.rel="noopener";v.textContent="View";right.appendChild(v)}
    const d=document.createElement("a");d.href=href;d.textContent="Download";right.appendChild(d);row.append(left,right);box.appendChild(row)});
}
async function poll(){clearTimeout(timer);let s;try{s=await api("/api/state");render(s)}catch(e){$("err").textContent=e.message}
  timer=setTimeout(poll,s&&s.running?1500:6000)}
async function go(dry){$("err").textContent="";save();try{render(await api("/api/start",payload(dry)));poll()}catch(e){$("err").textContent=e.message}}
$("start").onclick=()=>go(false);$("preview").onclick=()=>go(true);
$("stop").onclick=async()=>{try{render(await api("/api/stop",{}));poll()}catch(e){$("err").textContent=e.message}};
document.addEventListener("change",save);poll();
</script></body></html>
"""
