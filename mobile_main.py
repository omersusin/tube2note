"""tube2note mobile (Flet 1.x): paste a YouTube link, get the transcript on your phone.

Runs the real pipeline in-process via tube2note.api (no server needed).
Build: `flet build apk` (CI builds it — see .github/workflows/flet.yml).
"""
import asyncio
import os

import flet as ft

import tube2note.api as api


def _diag():
    """One-line startup diagnostics (decides storage/SSL questions on device)."""
    import sqlite3  # noqa: F401  (probe import)

    import yt_dlp
    try:
        import certifi
        cafile = certifi.where()
    except Exception:
        cafile = "missing"
    return (f"HOME={os.environ.get('HOME')} XDG_CACHE={os.environ.get('XDG_CACHE_HOME')} "
            f"cwd={os.getcwd()} ~={os.path.expanduser('~')} "
            f"DATA={os.environ.get('FLET_APP_STORAGE_DATA')} "
            f"CACHE={os.environ.get('FLET_APP_STORAGE_CACHE')} "
            f"cafile={cafile} yt-dlp={yt_dlp.version.__version__} flet={ft.__version__}")


def _outdir():
    """First writable tube2note folder: app storage, home, or cwd."""
    for base in (os.environ.get("FLET_APP_STORAGE_DATA"),
                 os.path.expanduser("~"), os.getcwd()):
        if not base:
            continue
        p = os.path.join(base, "tube2note")
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".w")
            with open(probe, "w") as f:
                f.write("1")
            os.unlink(probe)
            return p
        except OSError:
            continue
    return os.path.join(os.getcwd(), "tube2note")


def main(page: ft.Page):
    page.title = "tube2note"
    page.scroll = ft.ScrollMode.AUTO
    print(_diag(), flush=True)
    url = ft.TextField(label="YouTube link (video / channel / playlist)", expand=True)
    lang = ft.TextField(label="Languages", value="tr,en", width=160)
    max_n = ft.TextField(label="Max videos", value="20", width=140)
    log = ft.Text("", selectable=True)
    bar = ft.ProgressBar(visible=False, expand=True)
    go = ft.Button(content="Download")

    async def run(_):
        go.disabled = True
        bar.visible = True
        log.value = "Working..."
        page.update()
        urls = [u for u in (url.value or "").replace(",", " ").split() if u]
        if not urls:
            log.value = "Paste a YouTube link first."
            go.disabled = False
            bar.visible = False
            page.update()
            return
        outdir = _outdir()
        try:
            n = max(1, int(max_n.value or 20))
        except ValueError:
            log.value = "Max videos must be a number."
            go.disabled = False
            bar.visible = False
            page.update()
            return
        try:
            code, res = await asyncio.to_thread(
                api.collect, urls, "mobile.md",
                None, {"outdir": outdir},
                **{"lang": lang.value or "tr,en", "max_n": n, "verbose": False},
            )
            log.value = (f"Done: {res.get('ok', 0)}/{res.get('total', 0)} videos.\n"
                         f"Saved to {outdir}/mobile.md\n"
                         f"(exit {code})")
        except Exception as e:  # noqa: BLE001 — show it, don't crash the app
            log.value = f"Failed: {e}"
        go.disabled = False
        bar.visible = False
        page.update()

    go.on_click = run
    page.add(
        ft.Text("tube2note", size=28, weight="bold"),
        ft.Text("YouTube to Markdown for NotebookLM", size=14),
        ft.Row([url]),
        ft.Row([lang, max_n, go]),
        bar,
        log,
    )


ft.run(main)
