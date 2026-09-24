"""Public backend for the static site. Thin wrapper over web.Job/build_argv.
Run: BACKEND_TOKEN=secret OUT_DIR=/tmp python -m tube2note.server_api
Needs: pip install fastapi uvicorn (backend only, core stays stdlib).
Render free = ephemeral FS (no disk). Fly needs 512MB (see fly.toml).
"""
import asyncio
import json
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlsplit

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
except ImportError:
    raise SystemExit("backend needs: pip install fastapi uvicorn (or use `tube2note serve` locally)")
from .web import Job, build_argv, list_files, resolve_served

TOK = os.environ.get("BACKEND_TOKEN", "")
if not TOK:  # fail closed: random per-boot token, like `serve` (never run open)
    TOK = secrets.token_urlsafe(24)
    print("BACKEND_TOKEN unset: generated random per-boot token", flush=True)
BASE = os.path.abspath(os.environ.get("OUT_DIR", "tube2note-out"))
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
JOBS = {}  # token -> (Job, timestamp)
try:
    MAX_JOBS = max(1, min(32, int(os.environ.get("BACKEND_MAX_JOBS", "4"))))
except (TypeError, ValueError):
    MAX_JOBS = 4  # global cap on concurrent jobs
MAX_JOBS_ENTRIES = 128  # total entries cap: dict-flood guard
_JOBS_LOCK = asyncio.Lock()


def _prune_jobs(now):
    for k in [k for k, (_, t) in JOBS.items() if now - t > 24 * 3600]:
        JOBS.pop(k, None)
    while len(JOBS) > MAX_JOBS_ENTRIES:
        oldest = min(JOBS, key=lambda k: JOBS[k][1])
        try:
            JOBS[oldest][0].stop()
        except Exception:
            pass
        JOBS.pop(oldest, None)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-Token"])

@app.exception_handler(HTTPException)
async def _err_json(request, exc):
    # compat: both {error:} (our JS) and {detail:} (FastAPI default)
    return JSONResponse(status_code=exc.status_code,
                        content={"error": str(exc.detail), "detail": str(exc.detail)})

def _auth(tok):
    import secrets
    if not isinstance(tok, str) or not secrets.compare_digest(tok, TOK):
        raise HTTPException(401, "bad token")

def _ok(u):
    try:
        s = urlsplit(str(u).strip())
    except ValueError:
        return False
    return s.scheme in ("http", "https") and (s.hostname or "").lower() in HOSTS

def _is_trusted_proxy(host):
    h = (host or "").strip().lower().strip("[]")
    if h in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return True
    if h.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
                      "172.2", "172.30.", "172.31.", "fc", "fd", "fe80:")):
        # private nets (docker/fly/render gateways); explicit TRUSTED_PROXIES wins below
        return True
    extra = os.environ.get("TRUSTED_PROXIES", "")
    return bool(extra) and h in {x.strip().lower().strip("[]") for x in extra.split(",") if x.strip()}

def _ip(req: Request):
    # only trust proxy headers when the direct peer is a known proxy; else use direct peer
    direct = req.client.host if req.client else "?"
    if not _is_trusted_proxy(direct):
        return direct
    fci = req.headers.get("fly-client-ip", "").strip()
    if fci:
        return fci.split(",")[0].strip()
    xff = req.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return direct

def _live(j):
    return j is not None and j[0].running

@app.post("/api/start")
async def start(req: Request, x_token: Optional[str] = Header(None)):
    _auth(x_token)
    body = await req.body()
    if len(body) > 64 * 1024:
        raise HTTPException(413, "body too large")
    try:
        p = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(400, "invalid JSON")
    if not isinstance(p, dict):
        raise HTTPException(400, "JSON body must be an object")
    urls = p.get("urls") or []
    if not isinstance(urls, list):
        raise HTTPException(400, "urls must be a list")
    if not urls or len(urls) > 50 or any(not _ok(u) for u in urls):
        raise HTTPException(400, "need 1-50 youtube.com/youtu.be urls")
    tok = x_token or ""
    now = time.time()
    try:
        argv = build_argv(p, BASE)
    except ValueError as e:
        raise HTTPException(400, str(e))
    os.makedirs(BASE, exist_ok=True)
    async with _JOBS_LOCK:
        _prune_jobs(now)
        if _live(JOBS.get(tok)):
            raise HTTPException(409, "job already running")
        live = sum(1 for j in JOBS.values() if _live(j))
        if live >= MAX_JOBS:
            raise HTTPException(503, "server busy, try again later")
        JOBS[tok] = (Job(argv, argv[argv.index("-o") + 1], "--dry-run" in argv), now)
    return {"ok": True}


@app.post("/api/stop")
async def stop(req: Request, x_token: Optional[str] = Header(None)):
    _auth(x_token)
    async with _JOBS_LOCK:
        j = JOBS.get(x_token or "")
    if j:
        j[0].stop()
    return {"ok": True}


@app.get("/api/state")
async def state(req: Request, x_token: Optional[str] = Header(None)):
    _auth(x_token)
    async with _JOBS_LOCK:
        j = JOBS.get(x_token or "")
    return {"job": j[0].snapshot() if j else None, "files": list_files(BASE)}


@app.get("/api/download")
def dl(path: str, x_token: Optional[str] = Header(None)):
    _auth(x_token)  # header-only: tokens never travel in URLs
    full = resolve_served(BASE, path)
    if not full:
        raise HTTPException(404, "not found")
    return FileResponse(full)


@app.get("/healthz")
def healthz():
    return {"ok": True}

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                proxy_headers=True,
                forwarded_allow_ips=os.environ.get("TRUSTED_PROXIES", "127.0.0.1,::1"))

if __name__ == "__main__":
    main()
