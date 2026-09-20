"""Public backend for the static site. Thin wrapper over web.Job/build_argv.
Run: BACKEND_TOKEN=secret OUT_DIR=/tmp python -m tube2note.server_api
Needs: pip install fastapi uvicorn (backend only, core stays stdlib).
Render free = ephemeral FS (no disk). Fly needs 512MB (see fly.toml).
"""
import json
import os
import secrets
import time
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
    print(f"BACKEND_TOKEN unset: generated {TOK}", flush=True)
BASE = os.path.abspath(os.environ.get("OUT_DIR", "tube2note-out"))
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
JOBS = {}  # ip -> (Job, timestamp)
MAX_JOBS = int(os.environ.get("BACKEND_MAX_JOBS", "4"))  # global cap: no fork-bombs via spoofed IP headers

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-Token"])

@app.exception_handler(HTTPException)
async def _err_json(request, exc):
    # compat: both {error:} (our JS) and {detail:} (FastAPI default)
    return JSONResponse(status_code=exc.status_code,
                        content={"error": str(exc.detail), "detail": str(exc.detail)})

def _auth(tok):
    if tok != TOK:
        raise HTTPException(401, "bad token")

def _ok(u):
    try:
        s = urlsplit(str(u).strip())
    except ValueError:
        return False
    return s.scheme in ("http", "https") and (s.hostname or "").lower() in HOSTS

def _ip(req: Request):
    # trusted-proxy order: Fly-Client-IP, X-Forwarded-For first, else direct
    fci = req.headers.get("fly-client-ip", "").strip()
    if fci:
        return fci.split(",")[0].strip()
    xff = req.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return req.client.host if req.client else "?"

def _live(j):
    return j is not None and j[0].running

@app.post("/api/start")
async def start(req: Request, x_token: str | None = Header(None)):
    _auth(x_token)
    body = await req.body()
    if len(body) > 64 * 1024:
        raise HTTPException(413, "body too large")
    try:
        p = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(400, "invalid JSON")
    urls = p.get("urls") or []
    if isinstance(urls, str):
        urls = urls.split()
    if not urls or len(urls) > 50 or any(not _ok(u) for u in urls):
        raise HTTPException(400, "need 1-50 youtube.com/youtu.be urls")
    ip = _ip(req)
    now = time.time()
    for k in [k for k, (_, t) in JOBS.items() if now - t > 24 * 3600]:
        JOBS.pop(k, None)
    if _live(JOBS.get(ip)):
        raise HTTPException(409, "job already running")
    live = sum(1 for j in JOBS.values() if _live(j))
    if live >= MAX_JOBS:
        raise HTTPException(503, "server busy, try again later")
    try:
        argv = build_argv(p, BASE)
    except ValueError as e:
        raise HTTPException(400, str(e))
    os.makedirs(BASE, exist_ok=True)
    JOBS[ip] = (Job(argv, argv[argv.index("-o") + 1], "--dry-run" in argv), now)
    return {"ok": True}

@app.post("/api/stop")
async def stop(req: Request, x_token: str | None = Header(None)):
    _auth(x_token)
    j = JOBS.get(_ip(req))
    if j:
        j[0].stop()
    return {"ok": True}

@app.get("/api/state")
def state(req: Request, x_token: str | None = Header(None)):
    _auth(x_token)
    j = JOBS.get(_ip(req))
    return {"job": j[0].snapshot() if j else None, "files": list_files(BASE)}

@app.get("/api/download")
def dl(path: str, t: str | None = None, x_token: str | None = Header(None)):
    _auth(t or x_token)  # browsers can't set headers on <a> navigation: ?t= fallback
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
                proxy_headers=True, forwarded_allow_ips="*")

if __name__ == "__main__":
    main()
