"""tube2note mobile (Flet): paste a YouTube link, get the transcript on your phone.

Runs the real pipeline in-process via tube2note.api (no server needed).
Build: `flet build apk` (CI builds it — see .github/workflows/flet.yml).
"""
import os
import threading

import flet as ft

import tube2note.api as api


def main(page: ft.Page):
    page.title = "tube2note"
    page.scroll = "auto"
    url = ft.TextField(label="YouTube link (video / channel / playlist)", expand=True)
    lang = ft.TextField(label="Languages", value="tr,en", width=160)
    max_n = ft.TextField(label="Max videos", value="20", width=140)
    log = ft.Text("", selectable=True)
    bar = ft.ProgressBar(visible=False, expand=True)
    go = ft.ElevatedButton("Download")

    def run(_):
        go.disabled = True
        bar.visible = True
        log.value = "Working..."
        page.update()
        outdir = os.path.join(os.path.expanduser("~"), "tube2note")
        try:
            code, res = api.collect(
                [u for u in url.value.replace(",", " ").split() if u],
                out="mobile.md",
                overrides={"outdir": outdir},
                lang=lang.value or "tr,en",
                max_n=max(1, int(max_n.value or 20)),
                verbose=False,
            )
            log.value = (f"Done: {res.get('ok', 0)}/{res.get('total', 0)} videos.\n"
                         f"Saved to {outdir}/mobile.md\n"
                         f"(exit {code})")
        except ValueError:
            log.value = "Max videos must be a number."
        except Exception as e:  # noqa: BLE001 — show it, don't crash the app
            log.value = f"Failed: {e}"
        go.disabled = False
        bar.visible = False
        page.update()

    go.on_click = lambda e: threading.Thread(target=run, args=(e,), daemon=True).start()
    page.add(
        ft.Text("tube2note", size=28, weight="bold"),
        ft.Text("YouTube → Markdown for NotebookLM", size=14),
        ft.Row([url]),
        ft.Row([lang, max_n, go]),
        bar,
        log,
    )


if __name__ == "__main__":
    ft.app(target=main)
