"""tube2note mobile (Flet 1.x): paste a YouTube link, get the transcript on your phone.

Runs the real pipeline in-process via tube2note.api (no server needed).
Build: `flet build apk` (CI builds it — see .github/workflows/flet.yml).
"""
import asyncio
import os
import re

import flet as ft

import tube2note.api as api

KEY_NEED = "needs GEMINI_API_KEY (free at aistudio.google.com; core download is free)"


def _diag():
    """One-line startup diagnostics (decides storage/SSL questions on device)."""
    try:
        import sqlite3  # noqa: F401  (probe import)

        import yt_dlp
        yv = yt_dlp.version.__version__
    except Exception:
        yv = "?"
    try:
        import certifi
        cafile = certifi.where()
    except Exception:
        cafile = "missing"
    fv = getattr(ft, "__version__", "?")
    return (f"HOME={os.environ.get('HOME')} XDG_CACHE={os.environ.get('XDG_CACHE_HOME')} "
            f"cwd={os.getcwd()} ~={os.path.expanduser('~')} "
            f"DATA={os.environ.get('FLET_APP_STORAGE_DATA')} "
            f"CACHE={os.environ.get('FLET_APP_STORAGE_CACHE')} "
            f"cafile={cafile} yt-dlp={yv} flet={fv}")


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
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed="#d92d20")
    page.bgcolor = "#0d1017"
    page.padding = 16
    _CARD = "#161a22"
    _MUTED = "#8b95a5"

    def _section(t):
        return ft.Text(t, size=12, weight=ft.FontWeight.BOLD, color=_MUTED)

    def _card(*items):
        return ft.Container(
            content=ft.Column(list(items), spacing=10),
            bgcolor=_CARD,
            border_radius=12,
            padding=12,
        )
    print(_diag(), flush=True)
    url = ft.TextField(label="YouTube link (video / channel / playlist)", expand=True)
    out_name = ft.TextField(label="Output name (empty = video title)", value="", width=220, expand=True)
    lang = ft.TextField(label="Languages", value="tr,en", width=160, expand=True)
    max_n = ft.TextField(label="Max videos", value="20", width=140, expand=True)
    layout = ft.Dropdown(label="Layout", value="single", width=160, expand=True,
                         options=[ft.dropdown.Option("single"), ft.dropdown.Option("videos"),
                                  ft.dropdown.Option("tree")])
    since = ft.TextField(label="Since (YYYY-MM-DD)", width=180, expand=True)
    split_n = ft.TextField(label="Split words (0=off)", value="0", width=160, expand=True)
    workers_n = ft.TextField(label="Workers (1=safest)", value="1", width=160, expand=True)
    timestamps = ft.Checkbox(label="Keep [MM:SS] timestamps", value=False)
    link_ts = ft.Checkbox(label="Clickable timestamp links", value=False)
    srt = ft.Checkbox(label="Write .srt sidecars", value=False)
    clean = ft.Checkbox(label="Clean transcripts", value=True)
    pdf = ft.Checkbox(label="Also write PDF", value=False)
    epub = ft.Checkbox(label="Also write EPUB", value=False)
    ai_note = ft.Text("AI needs a key below (free). Core download is free.",
                      size=12, color=ft.Colors.ON_SURFACE_VARIANT)
    tr_summarize = ft.Checkbox(label="Summarize each video", value=False)
    tr_transcribe = ft.Checkbox(label="Transcribe videos without captions", value=False)
    tr_translate = ft.TextField(label="Translate to (e.g. tr, empty=off)", width=220, expand=True)
    tr_bilingual = ft.TextField(label="Bilingual (e.g. tr, empty=off)",
                                width=220, expand=True)
    gemini_key = ft.TextField(label="GEMINI_API_KEY (free)",
                              helper_text="Get it at aistudio.google.com",
                              password=True,
                              can_reveal_password=True, expand=True)
    log = ft.Text("", selectable=True, font_family="monospace")
    bar = ft.ProgressBar(visible=False, expand=True)
    go = ft.Button(content="Download", expand=True, height=52)
    preview = ft.Button(content="Preview", expand=True, height=48)
    files_list = ft.Text("", selectable=True)

    def out_file():
        from tube2note.naming import sanitize_filename
        name = (out_name.value or "").strip()
        if not name:
            return ""  # resolved from video title at run time
        name = sanitize_filename(name) or "tube2note"
        return name if name.lower().endswith(".md") else name + ".md"

    async def resolve_name(urls):
        from tube2note.naming import slug
        if out_file():
            return out_file()
        try:
            vids, hint = await asyncio.to_thread(api.list_videos, urls, 5, None)
            title = hint or (vids[0].get("title") if vids else "") or "tube2note"
            return slug(title)
        except Exception:  # noqa: BLE001 — fall back, never block the run
            return "tube2note.md"

    def refresh_files():
        d = _outdir()
        try:
            items = sorted(os.listdir(d))
        except OSError:
            items = []
        rows = []
        for f in items:
            if f.startswith("."):
                continue
            if f.lower().endswith((".md", ".pdf", ".epub")):
                try:
                    kb = os.path.getsize(os.path.join(d, f)) // 1024
                except OSError:
                    kb = 0
                rows.append(f"{f} ({kb} KB)")
        files_list.value = "Files:\n" + ("\n".join(rows) if rows else "Nothing here yet.")
        page.update()

    async def do_preview(_):
        go.disabled = True
        preview.disabled = True
        urls = [u for u in (url.value or "").replace(",", " ").split() if u]
        if not urls:
            log.value = "Paste a YouTube link first."
            go.disabled = False
            preview.disabled = False
            page.update()
            return
        log.value = "Listing..."
        page.update()
        try:
            since_s = (since.value or "").strip() or None
            if since_s and not re.match(r"^\d{4}-\d{2}-\d{2}$", since_s):
                log.value = "Since must be YYYY-MM-DD."
            else:
                try:
                    n = min(5000, max(1, int(max_n.value or 20)))
                except (TypeError, ValueError):
                    n = 20
                vids, _hint = await asyncio.to_thread(api.list_videos, urls, n, since_s)
                langs = await asyncio.to_thread(api.language_hint, vids)
                sug = langs[0] if isinstance(langs, tuple) else langs
                log.value = (f"Preview: {len(vids)} videos, languages: {sug}\n"
                             f"Output: {out_file() or 'auto (video title)'}")
        except Exception as e:  # noqa: BLE001
            log.value = f"Preview failed: {e}"
        go.disabled = False
        preview.disabled = False
        page.update()

    async def run(_):
        go.disabled = True
        preview.disabled = True
        bar.visible = True
        log.value = "Working..."
        page.update()
        urls = [u for u in (url.value or "").replace(",", " ").split() if u]
        if not urls:
            log.value = "Paste a YouTube link first."
            go.disabled = False
            preview.disabled = False
            bar.visible = False
            page.update()
            return
        outdir = _outdir()
        if (gemini_key.value or "").strip():
            os.environ["GEMINI_API_KEY"] = gemini_key.value.strip()
        ai = {"transcribe": bool(tr_transcribe.value), "summarize": bool(tr_summarize.value),
              "translate": (tr_translate.value or "").strip() or None,
              "bilingual": (tr_bilingual.value or "").strip() or None}
        if ai["translate"] and ai["bilingual"]:
            log.value = "Translate and bilingual are mutually exclusive — pick one."
            go.disabled = False
            preview.disabled = False
            bar.visible = False
            page.update()
            return
        if (ai["transcribe"] or ai["summarize"] or ai["translate"] or ai["bilingual"]) \
                and not os.environ.get("GEMINI_API_KEY"):
            log.value = f"AI {KEY_NEED} — paste it above."
            go.disabled = False
            preview.disabled = False
            bar.visible = False
            page.update()
            return
        try:
            n = min(5000, max(1, int(max_n.value or 20)))
            split = min(500000, max(0, int(split_n.value or 0)))
            wk = min(4, max(1, int(workers_n.value or 1)))
        except (TypeError, ValueError):
            log.value = "Max videos / split / workers must be numbers (max 1-5000, split 0-500000, workers 1-4)."
            go.disabled = False
            preview.disabled = False
            bar.visible = False
            page.update()
            return
        since_s = (since.value or "").strip() or None
        if since_s and not re.match(r"^\d{4}-\d{2}-\d{2}$", since_s):
            log.value = "Since must be YYYY-MM-DD."
            go.disabled = False
            preview.disabled = False
            bar.visible = False
            page.update()
            return
        lay = layout.value if layout.value in ("single", "videos", "tree") else "single"
        try:
            fname = await resolve_name(urls)
            code, res = await asyncio.to_thread(
                api.collect, urls, fname,
                None, {"outdir": outdir},
                **{"lang": (lang.value or "tr,en").strip() or "tr,en", "max_n": n, "verbose": False,
                   "layout": lay,
                   "since": since_s,
                   "split_words": split, "workers": wk,
                   "ts": bool(timestamps.value), "link_timestamps": bool(link_ts.value),
                   "srt": bool(srt.value), "clean": bool(clean.value),
                   "pdf": bool(pdf.value), "epub": bool(epub.value),
                   **ai},
            )
            log.value = (f"Done: {res.get('ok', 0)}/{res.get('total', 0)} videos.\n"
                         f"Saved to {outdir}/{fname}\n"
                         f"(exit {code})")
        except Exception as e:  # noqa: BLE001 — show it, don't crash the app
            log.value = f"Failed: {e}"
        refresh_files()
        go.disabled = False
        preview.disabled = False
        bar.visible = False
        page.update()

    go.on_click = run
    preview.on_click = do_preview
    page.add(
        ft.Column(
            [
                _card(
                    ft.Text("tube2note", size=28, weight=ft.FontWeight.BOLD, color="#e8ecf1"),
                    ft.Text("YouTube to Markdown for NotebookLM", size=14, color="#8b95a5"),
                ),
                _section("SOURCE"),
                _card(
                    url,
                    ft.Text("Paste a video, channel, or playlist link.", size=12, color="#8b95a5"),
                ),
                _section("OUTPUT"),
                _card(
                    out_name,
                    lang,
                    max_n,
                    layout,
                    since,
                    split_n,
                    workers_n,
                    timestamps, link_ts, srt, clean, pdf, epub,
                    ft.Text("Options apply to every download.", size=12, color="#8b95a5"),
                ),
                _section("AI (needs key)"),
                _card(
                    ai_note,
                    tr_transcribe, tr_summarize,
                    tr_translate, tr_bilingual,
                    gemini_key,
                ),
                _section("ACTIONS"),
                _card(
                    go,
                    preview,
                    bar,
                ),
                _section("FILES"),
                _card(files_list),
                _section("LOG"),
                _card(log),
            ],
            spacing=12,
        ),
    )
    refresh_files()


ft.run(main)
