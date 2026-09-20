"""`tube2note serve`: auth, request validation, file serving, and a real end-to-end job against the fake yt-dlp."""
import http.client
import json
import os
import sys
import threading
import time

import pytest

from tube2note import web

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
LIST = "https://www.youtube.com/playlist?list=PLfake"
TOKEN = "TESTTOKEN"


class Client:
    def __init__(self, srv):
        self.port = srv.server_address[1]
        self.cookie = None

    def req(self, method, path, body=None, headers=None, auth=True, ctype="application/json"):
        h = {"Host": f"127.0.0.1:{self.port}"}
        if auth and self.cookie:
            h["Cookie"] = self.cookie
        if body is not None:
            h["Content-Type"] = ctype
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=None if body is None else (body if isinstance(body, bytes) else json.dumps(body)),
                  headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def login(self):
        st, hd, _ = self.req("GET", f"/?t={TOKEN}", auth=False)
        assert st == 302
        self.cookie = hd["Set-Cookie"].split(";")[0]

    def json(self, method, path, body=None, **kw):
        st, _, data = self.req(method, path, body, **kw)
        return st, json.loads(data or b"{}")


@pytest.fixture
def make(tmp_path):
    servers = []

    def _make(argv_builder=web.build_argv):
        base = tmp_path / "out"
        srv = web.make_server(str(base), "127.0.0.1", 0, TOKEN, argv_builder)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        c = Client(srv)
        c.base = base
        c.srv = srv
        return c

    yield _make
    for s in servers:
        s.app.stop()
        s.shutdown()
        s.server_close()


def wait_for(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.1)
    raise AssertionError("timed out")


# ---------------------------------------------------------------- auth & headers

def test_requires_token(make):
    c = make()
    assert c.req("GET", "/api/state", auth=False)[0] == 401
    assert c.req("GET", "/", auth=False)[0] == 401
    assert c.req("GET", "/?t=wrong", auth=False)[0] == 401
    c.login()
    st, body = c.json("GET", "/api/state")
    assert st == 200 and body["running"] is False and body["files"] == []
    st, hd, page = c.req("GET", "/")
    assert st == 200 and b"tube2note" in page
    assert "nonce-" in hd["Content-Security-Policy"] and "unsafe-inline" not in hd["Content-Security-Policy"]
    assert b"__NONCE__" not in page


def test_cookie_is_httponly_samesite(make):
    c = make()
    _, hd, _ = c.req("GET", f"/?t={TOKEN}", auth=False)
    assert "HttpOnly" in hd["Set-Cookie"] and "SameSite=Strict" in hd["Set-Cookie"]


def test_rejects_foreign_host_header(make):
    c = make()
    c.login()
    assert c.req("GET", "/api/state", headers={"Host": "evil.example"})[0] == 403


def test_csrf_protections(make):
    c = make()
    c.login()
    body = {"urls": [LIST]}
    assert c.req("POST", "/api/start", body, headers={"Origin": "http://evil.example"})[0] == 403
    assert c.req("POST", "/api/start", json.dumps(body).encode(), ctype="text/plain")[0] == 415
    assert c.req("POST", "/api/start", body, auth=False)[0] == 401


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("payload,msg", [
    ({"urls": []}, "at least one"),
    ({"urls": ["--proxy=http://evil"]}, "Not a YouTube URL"),
    ({"urls": ["https://evil.example/watch?v=aaaaaaaaaaa"]}, "Not a YouTube URL"),
    ({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"], "layout": "../../x"}, "layout"),
    ({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"], "lang": "en; rm -rf"}, "Language"),
    ({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"], "since": "yesterday"}, "YYYY-MM-DD"),
    ({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"], "max": 999999}, "Max videos"),
    ({"urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"], "workers": 9}, "Workers"),
])
def test_build_argv_rejects(payload, msg):
    with pytest.raises(ValueError, match=msg):
        web.build_argv(payload, "/tmp/x")


def test_build_argv_shape(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    argv = web.build_argv({"urls": [LIST, "https://youtu.be/aaaaaaaaaaa"], "name": "../../etc/passwd", "layout": "tree",
                           "lang": "tr,en", "max": "20", "timestamps": True, "clean": False, "split_words": "1000",
                           "workers": "2", "summarize": True, "translate": "tr"}, "/data/out")
    assert argv[argv.index("-d") + 1] == "/data/out"      # output folder is fixed by the server, never by the page
    name = argv[argv.index("-o") + 1]
    assert name.endswith(".md") and os.path.basename(name) == name and not name.startswith(".")
    assert "--no-clean" in argv and "--timestamps" in argv and argv[argv.index("--workers") + 1] == "2"
    assert "--summarize" not in argv and "--translate" not in argv     # no key on the server -> no Gemini flags
    sep = argv.index("--")
    assert argv[sep + 1:] == [LIST, "https://youtu.be/aaaaaaaaaaa"]      # URLs only after `--`
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    argv = web.build_argv({"urls": [LIST], "summarize": True, "translate": "tr"}, "/d")
    assert "--summarize" in argv and argv[argv.index("--translate") + 1] == "tr"
    with pytest.raises(ValueError):
        web.build_argv({"urls": [LIST], "translate": "tr; x"}, "/d")


# ---------------------------------------------------------------- files

def test_file_serving_and_traversal(make, tmp_path):
    c = make()
    c.login()
    base = c.base
    (base / "sub").mkdir(parents=True)
    (base / "a.md").write_text("# hello ünï\n", encoding="utf-8")
    (base / "a.md.done").write_text("x\n")
    (base / "sub" / "b.pdf").write_bytes(b"%PDF-fake")
    (tmp_path / "secret.md").write_text("SECRET")
    os.symlink(tmp_path / "secret.md", base / "link.md")
    st, hd, data = c.req("GET", "/files/a.md")
    assert st == 200 and data.decode() == "# hello ünï\n" and "attachment" in hd["Content-Disposition"]
    st, hd, data = c.req("GET", "/files/a.md?view=1")
    assert st == 200 and hd["Content-Type"].startswith("text/plain")
    assert c.req("GET", "/files/sub/b.pdf")[0] == 200
    for bad in ["/files/../secret.md", "/files/..%2fsecret.md", "/files/%2e%2e/secret.md", "/files//etc/passwd",
                "/files/link.md", "/files/a.md.done", "/files/sub", "/files/nope.md", "/files/a.md%00.pdf"]:
        assert c.req("GET", bad)[0] in (403, 404), bad
    assert c.req("GET", "/files/a.md", auth=False)[0] == 401
    st, body = c.json("GET", "/api/state")
    paths = {f["path"]: f for f in body["files"]}
    assert set(paths) == {"a.md", "sub/b.pdf"}          # the symlink that escapes the folder is not even listed
    assert paths["a.md"]["done"] == 1


# ---------------------------------------------------------------- jobs

def fake_builder(script):
    return lambda payload, base: [sys.executable, "-u", "-c", script]


def test_one_job_at_a_time_and_stop(make):
    c = make(fake_builder("import time\nprint('[1/5] Some video', flush=True)\n"
                          "print('1/5 videos · 10 words · 0 min', flush=True)\ntime.sleep(60)"))
    c.login()
    assert c.json("POST", "/api/start", {"urls": [LIST]})[0] == 200
    st, s = c.json("GET", "/api/state")
    wait_for(lambda: c.json("GET", "/api/state")[1]["job"]["progress"]["total"] == 5)
    s = c.json("GET", "/api/state")[1]
    assert s["running"] and s["job"]["current"] == "Some video" and s["job"]["progress"]["done"] == 1
    assert c.json("POST", "/api/start", {"urls": [LIST]})[0] == 409
    c.json("POST", "/api/stop", {})
    s = wait_for(lambda: (lambda j: j if not j["running"] else None)(c.json("GET", "/api/state")[1]))
    assert s["job"]["state"] == "stopped"


def test_failed_job_state(make):
    c = make(fake_builder("import sys; print('boom'); sys.exit(3)"))
    c.login()
    c.json("POST", "/api/start", {"urls": [LIST]})
    s = wait_for(lambda: (lambda j: j if not j["running"] else None)(c.json("GET", "/api/state")[1]))
    assert s["job"]["state"] == "failed" and s["job"]["returncode"] == 3 and "boom" in s["job"]["log"]


def test_end_to_end_with_real_subprocess(make, home, monkeypatch, tmp_path):
    """Start a job from the 'browser', let the real CLI run in a subprocess against the fake yt-dlp, download the result."""
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text(
        f"import sys\nsys.path.insert(0, {TESTS!r})\nimport fake_ydl\nfake_ydl.install()\n")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(shim), ROOT]))
    c = make()
    c.login()
    st, body = c.json("POST", "/api/start", {"urls": [LIST], "name": "web.md", "lang": "en,tr", "max": 10})
    assert st == 200, body
    s = wait_for(lambda: (lambda j: j if j["job"] and not j["running"] else None)(c.json("GET", "/api/state")[1]), 60)
    assert s["job"]["state"] == "done", "\n".join(s["job"]["log"])
    assert s["job"]["progress"]["done"] == s["job"]["progress"]["total"] == 4
    f = {x["path"]: x for x in s["files"]}["web.md"]
    assert f["done"] == 3 and f["skipped"] == 1
    st, _, md = c.req("GET", "/files/web.md")
    assert st == 200 and b"Hello and welcome to the show." in md
