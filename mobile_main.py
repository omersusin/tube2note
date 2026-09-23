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
    out_name = ft.TextField(label="Output name", value="mobile.md", width=220)
    lang = ft.TextField(label="Languages", value="tr,en", width=160)
    max_n = ft.TextField(label="Max videos", value="20", width=140)
    layout = ft.Dropdown(label="Layout", value="single", width=160,
                         options=[ft.dropdown.Option("single"), ft.dropdown.Option("videos"),
                                  ft.dropdown.Option("tree")])
    since = ft.TextField(label="Since (YYYY-MM-DD)", width=180)
    split_n = ft.TextField(label="Split words (0=off)", value="0", width=160)
    workers_n = ft.TextField(label="Workers (1=safest)", value="1", width=160)
    timestamps = ft.Checkbox(label="Keep [MM:SS] timestamps", value=False)
    link_ts = ft.Checkbox(label="Clickable timestamp links", value=False)
    srt = ft.Checkbox(label="Write .srt sidecars", value=False)
    clean = ft.Checkbox(label="Clean transcripts", value=True)
    pdf = ft.Checkbox(label="Also write PDF", value=False)
    epub = ft.Checkbox(label="Also write EPUB", value=False)
    log = ft.Text("", selectable=True)
    bar = ft.ProgressBar(visible=False, expand=True)
    go = ft.Button(content="Download")
    preview = ft.Button(content="Preview")
    files_list = ft.Text("", selectable=True)

    def out_file():
        name = (out_name.value or "mobile.md").strip() or "mobile.md"
        return name if name.lower().endswith(".md") else name + ".md"

    def refresh_files():
        d = _outdir()
        try:
            items = sorted(os.listdir(d))
        except OSError:
            items = []
        rows = []
        for f in items:
            if f.endswith(".md"):
                try:
                    kb = os.path.getsize(os.path.join(d, f)) // 1024
                except OSError:
                    kb = 0
                rows.append(f"{f} ({kb} KB)")
        files_list.value = "Files:\n" + ("\n".join(rows) if rows else "Nothing here yet.")

    async def do_preview(_):
        urls = [u for u in (url.value or "").replace(",", " ").split() if u]
        if not urls:
            log.value = "Paste a YouTube link first."
            page.update()
            return
        log.value = "Listing..."
        page.update()
        try:
            vids, _hint = await asyncio.to_thread(api.list_videos, urls, 100, None)
            langs = await asyncio.to_thread(api.language_hint, vids)
            sug = langs[0] if isinstance(langs, tuple) else langs
            log.value = (f"Preview: {len(vids)} videos, languages: {sug}\n"
                         f"Output: {out_file()}")
        except Exception as e:  # noqa: BLE001
            log.value = f"Preview failed: {e}"
        page.update()

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
            split = max(0, int(split_n.value or 0))
            wk = min(4, max(1, int(workers_n.value or 1)))
        except ValueError:
            log.value = "Max videos / split / workers must be numbers."
            go.disabled = False
            bar.visible = False
            page.update()
            return
        try:
            code, res = await asyncio.to_thread(
                api.collect, urls, out_file(),
                None, {"outdir": outdir},
                **{"lang": lang.value or "tr,en", "max_n": n, "verbose": False,
                   "layout": layout.value or "single",
                   "since": since.value.strip() or None,
                   "split_words": split, "workers": wk,
                   "ts": timestamps.value, "link_timestamps": link_ts.value,
                   "srt": srt.value, "clean": clean.value,
                   "pdf": pdf.value, "epub": epub.value},
            )
            log.value = (f"Done: {res.get('ok', 0)}/{res.get('total', 0)} videos.\n"
                         f"Saved to {outdir}/{out_file()}\n"
                         f"(exit {code})")
        except Exception as e:  # noqa: BLE001 — show it, don't crash the app
            log.value = f"Failed: {e}"
        refresh_files()
        go.disabled = False
        bar.visible = False
        page.update()

    go.on_click = run
    preview.on_click = do_preview
    page.add(
        ft.Text("tube2note", size=28, weight="bold"),
        ft.Text("YouTube to Markdown for NotebookLM", size=14),
        ft.Row([url]),
        ft.Row([out_name, lang, max_n, go]),
        ft.Row([layout, since]),
        ft.Row([split_n, workers_n]),
        timestamps, link_ts, srt, clean, pdf, epub,
        ft.Row([preview]),
        files_list,
        bar,
        log,
    )
    refresh_files()


ft.run(main)
