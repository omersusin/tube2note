"""Backend API tests. Skipped unless the backend extra is installed.

Backend devs: pip install fastapi uvicorn httpx
"""
import importlib.util

import pytest

pytestmark = pytest.mark.skipif(importlib.util.find_spec("fastapi") is None,
                                reason="backend extra not installed (pip install fastapi uvicorn httpx)")

import importlib  # noqa: E402  (after skip guard by design)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_TOKEN", "test-token")
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_MAX_JOBS", "4")
    import tube2note.server_api as api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    return TestClient(api.app), api


def test_auth_fail_closed(client):
    c, _ = client
    assert c.post("/api/start", json={"urls": []}).status_code == 401
    assert c.post("/api/start", json={"urls": []}, headers={"X-Token": "wrong"}).status_code == 401
    assert c.get("/api/state", headers={"X-Token": "wrong"}).status_code == 401
    assert c.get("/api/download?path=x.md").status_code == 401


def test_random_token_when_unset(monkeypatch):
    monkeypatch.delenv("BACKEND_TOKEN", raising=False)
    import tube2note.server_api as api
    importlib.reload(api)
    assert api.TOK and len(api.TOK) >= 20


def test_ssrf_rejected(client):
    c, api = client
    h = {"X-Token": "test-token"}
    assert c.post("/api/start", json={"urls": ["http://169.254.169.254/"]}, headers=h).status_code == 400
    assert c.post("/api/start", json={"urls": ["https://youtube.com.evil.example/"]}, headers=h).status_code == 400
    assert c.post("/api/start", json={"urls": ["https://youtube.com@evil.example/"]}, headers=h).status_code == 400


def test_body_cap_and_url_cap(client):
    c, _ = client
    h = {"X-Token": "test-token", "Content-Type": "application/json"}
    r = c.post("/api/start", content=b"x" * (64 * 1024 + 1), headers=h)
    assert r.status_code == 413
    urls = ["https://www.youtube.com/watch?v=aaaaaaaaaaa"] * 51
    assert c.post("/api/start", json={"urls": urls}, headers={"X-Token": "test-token"}).status_code == 400


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
