"""Backend API tests. FastAPI tests skip without the backend extra;
stdlib tests below run everywhere (Termux-safe, no fastapi needed)."""
import importlib
import importlib.util
import sys
import types

import pytest

NEEDS_FASTAPI = pytest.mark.skipif(importlib.util.find_spec("fastapi") is None,
                                   reason="backend extra not installed (pip install fastapi uvicorn httpx)")


def _stub_fastapi():
    import importlib.machinery
    if "fastapi" in sys.modules:
        return
    if importlib.util.find_spec("fastapi") is not None:
        return

    class HTTPException(Exception):
        def __init__(self, status_code, detail=""):
            self.status_code, self.detail = status_code, detail
            super().__init__(detail)

    def Header(default=None):
        return default

    class Request:
        pass

    class FastAPI:
        def __init__(self, *a, **k):
            self.routes = []
        def add_middleware(self, *a, **k):
            pass
        def exception_handler(self, *a, **k):
            return lambda fn: fn
        def _reg(self, path, methods):
            def deco(fn):
                self.routes.append(types.SimpleNamespace(path=path, methods=methods, endpoint=fn))
                return fn
            return deco
        def get(self, path, **k):
            return self._reg(path, ["GET"])
        def post(self, path, **k):
            return self._reg(path, ["POST"])

    class CORSMiddleware:
        pass

    class FileResponse:
        def __init__(self, path):
            self.path = path

    class JSONResponse:
        def __init__(self, status_code=200, content=None):
            self.status_code, self.body = status_code, content

    fa = types.ModuleType("fastapi")
    fa.FastAPI, fa.Header, fa.HTTPException, fa.Request = FastAPI, Header, HTTPException, Request
    mid = types.ModuleType("fastapi.middleware.cors")
    mid.CORSMiddleware = CORSMiddleware
    mw = types.ModuleType("fastapi.middleware")
    mw.cors = mid
    res = types.ModuleType("fastapi.responses")
    res.FileResponse, res.JSONResponse = FileResponse, JSONResponse
    fa.__spec__ = importlib.machinery.ModuleSpec("fastapi", loader=None)
    mw.__spec__ = importlib.machinery.ModuleSpec("fastapi.middleware", loader=None)
    mid.__spec__ = importlib.machinery.ModuleSpec("fastapi.middleware.cors", loader=None)
    res.__spec__ = importlib.machinery.ModuleSpec("fastapi.responses", loader=None)
    sys.modules.update({"fastapi": fa, "fastapi.middleware": mw,
                        "fastapi.middleware.cors": mid, "fastapi.responses": res})


def _load_api(monkeypatch, tmp_path):
    _stub_fastapi()
    monkeypatch.setenv("BACKEND_TOKEN", "test-token")
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_MAX_JOBS", "4")
    import tube2note.server_api as api
    importlib.reload(api)
    api.JOBS.clear()
    return api


@pytest.fixture
def client(tmp_path, monkeypatch):
    if importlib.util.find_spec("fastapi") is None:
        pytest.skip("backend extra not installed (pip install fastapi uvicorn httpx)")
    monkeypatch.setenv("BACKEND_TOKEN", "test-token")
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_MAX_JOBS", "4")
    import tube2note.server_api as api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.app), api


@NEEDS_FASTAPI
def test_auth_fail_closed(client):
    c, _ = client
    assert c.post("/api/start", json={"urls": []}).status_code == 401
    assert c.post("/api/start", json={"urls": []}, headers={"X-Token": "wrong"}).status_code == 401
    assert c.get("/api/state", headers={"X-Token": "wrong"}).status_code == 401
    assert c.get("/api/download?path=x.md").status_code == 401


@NEEDS_FASTAPI
def test_random_token_when_unset(monkeypatch):
    monkeypatch.delenv("BACKEND_TOKEN", raising=False)
    import tube2note.server_api as api
    importlib.reload(api)
    assert api.TOK and len(api.TOK) >= 20


@NEEDS_FASTAPI
def test_ssrf_rejected(client):
    c, api = client
    h = {"X-Token": "test-token"}
    assert c.post("/api/start", json={"urls": ["http://169.254.169.254/"]}, headers=h).status_code == 400
    assert c.post("/api/start", json={"urls": ["https://youtube.com.evil.example/"]}, headers=h).status_code == 400
    assert c.post("/api/start", json={"urls": ["https://youtube.com@evil.example/"]}, headers=h).status_code == 400


@NEEDS_FASTAPI
def test_body_cap_and_url_cap(client):
    c, _ = client
    h = {"X-Token": "test-token", "Content-Type": "application/json"}
    r = c.post("/api/start", content=b"x" * (64 * 1024 + 1), headers=h)
    assert r.status_code == 413
    urls = ["https://www.youtube.com/watch?v=aaaaaaaaaaa"] * 51
    assert c.post("/api/start", json={"urls": urls}, headers={"X-Token": "test-token"}).status_code == 400


@NEEDS_FASTAPI
def test_healthz_open_and_download_token_query(client):
    c, api = client
    assert c.get("/healthz").status_code == 200
    base = api.BASE
    import os
    os.makedirs(base, exist_ok=True)
    open(os.path.join(base, "x.md"), "w").write("# hi\n")
    assert c.get("/api/download?path=x.md&t=test-token").status_code == 200
    assert c.get("/api/download?path=x.md&t=nope").status_code == 401
    assert c.get("/api/download?path=../x.md&t=test-token").status_code == 404


# ---------------------------------------------------------------- stdlib (no fastapi)

def test_stdlib_healthz_and_routes(tmp_path, monkeypatch):
    api = _load_api(monkeypatch, tmp_path)
    assert api.healthz() == {"ok": True}
    paths = {r.path for r in api.app.routes}
    assert {"/healthz", "/api/start", "/api/stop", "/api/state", "/api/download"} <= paths


def test_stdlib_auth(tmp_path, monkeypatch):
    api = _load_api(monkeypatch, tmp_path)
    api._auth("test-token")
    for bad in ("wrong", "", None, 123):
        try:
            api._auth(bad)
            raise AssertionError(f"should 401 for {bad!r}")
        except Exception as e:
            assert getattr(e, "status_code", None) == 401


def test_stdlib_ssrf(tmp_path, monkeypatch):
    api = _load_api(monkeypatch, tmp_path)
    for bad in ("http://169.254.169.254/", "https://youtube.com.evil.example/",
                "https://youtube.com@evil.example/", "http://evil.example/watch",
                "ftp://www.youtube.com/watch?v=aaaaaaaaaaa"):
        assert not api._ok(bad), bad
    for good in ("https://www.youtube.com/watch?v=aaaaaaaaaaa", "https://youtu.be/aaaaaaaaaaa",
                 "https://m.youtube.com/watch?v=aaaaaaaaaaa"):
        assert api._ok(good), good


def test_stdlib_body_and_url_caps(tmp_path, monkeypatch):
    import asyncio
    import json as _j
    api = _load_api(monkeypatch, tmp_path)

    class Req:
        headers = {}
        client = types.SimpleNamespace(host="127.0.0.1")
        def __init__(self, body):
            self._body = body
        async def body(self):
            return self._body

    async def code(body, tok="test-token"):
        try:
            await api.start(Req(body), tok)
            return 200
        except Exception as e:
            return getattr(e, "status_code", 500)

    assert asyncio.run(code(b"x" * (64 * 1024 + 1))) == 413
    assert asyncio.run(code(b"not json")) == 400
    bad = _j.dumps({"urls": ["http://169.254.169.254/"], "name": "x.md"}).encode()
    assert asyncio.run(code(bad)) == 400
    many = _j.dumps({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"] * 51,
                     "name": "x.md"}).encode()
    assert asyncio.run(code(many)) == 400
    assert asyncio.run(code(b"{}", tok="wrong")) == 401
