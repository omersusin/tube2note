# tube2note — YouTube → Markdown (and PDF) for NotebookLM

Turn a YouTube channel, playlist, or list of videos into **Markdown files** (or PDF) ready to feed NotebookLM / any RAG pipeline. Small and dependency-light (just `yt-dlp`), resumable, polite to YouTube's rate limits. Works from the command line, a guided terminal mode, or a local web page.

```bash
pip install tube2note yt-dlp
tube2note -o channel.md "https://www.youtube.com/@SomeChannel/videos"
# or guided mode (just type `tube2note`, answer a few questions):
tube2note
```

Prefer a page over a terminal? `tube2note serve` (see [Web UI](#web-ui)).

PDF too? `pip install "tube2note[pdf]"`, then add `--pdf` (or run `tube2note pdf existing.md`).

## Why not just paste YouTube links into NotebookLM?

- NotebookLM caps YouTube imports (~100 videos) and needs caption files per video.
- tube2note merges everything into sources you control: one file per 500k-word cap, timestamps, per-video files, resume after interruptions.

## Features

- **Channel / playlist / video URLs** (auto-detected listing, Shorts/tabs handled)
- **Guided TUI**: intro, first-run guide, auto-detected file name / video count / languages, confirm table, live dashboard (bar + current video + stats)
- **Anti-throttle engine**: chunks with breaks, jittered pacing, single retry on 429, long cooldown after 5 throttles in a row
- **Resume**: `.done` log — Ctrl+C anytime, continue later; skip log reconciled every run
- **Layouts**: `single` (one .md), `videos` (per-video files + `INDEX.md`), `tree` (`Channel/Video/transcript.md` + `INDEX.md` + YAML frontmatter)
- **Name templates**: `--name-template "{channel}/{title} [{id}]"` (fields: channel, title, id, index, date, lang)
- **Personalization**: `setup` wizard, named `--profile`s, `YT2MD_*` env vars, per-folder `.yt2md.json` overrides
- **NotebookLM-aware**: `--timestamps`, `--split-words` auto-split under the 500k-word cap, chapter-based sections, rich per-video metadata
- **Transcript cleaning** (default on, `--no-clean` to disable): filler words, repeated phrases, one sentence per line
- **Gemini extras** (needs free `GEMINI_API_KEY`): `--transcribe` for captionless videos, `--summarize` for per-video summaries, `--translate LANG`
- **Web UI**: `tube2note serve` opens a phone-friendly page to start, watch and stop jobs and download the results (stdlib only, works in Termux)
- **PDF export**: `--pdf` or `pdf file.md [...]` (needs `pip install "tube2note[pdf]"`)
- **Status & dry-run**: `status [dir]` progress table, `--dry-run` estimate before downloading
- **Smart & polite**: shared subtitle cache (`~/.cache/tube2note`), `--since` date filter, `--proxy`/`--cookies`, `doctor` diagnosis, Termux:Widget one-tap resume

## Quickstart

```bash
pip install tube2note yt-dlp
tube2note -o notes.md "<playlist_url>" "<video_url>" ...
tube2note -o channel.md --max 200 --layout tree -d ./out "https://www.youtube.com/@SomeChannel/videos"
tube2note status ./out
```

From source:

```bash
git clone https://github.com/omersusin/tube2note && cd tube2note
pip install -e ".[dev]"
python3 -m tube2note        # or just: tube2note
```

## Web UI

```bash
tube2note serve                 # opens http://127.0.0.1:8765 in your browser (Termux: via termux-open-url)
tube2note serve -d ~/notes      # choose the output folder
tube2note serve --no-open       # just print the link
```

Paste URLs, tap **Start**, watch progress, tap **View / Download** when it finishes. **Preview** runs `--dry-run`. Each job is a normal `tube2note` subprocess, so resume, layouts and throttling behave exactly like the CLI (re-use an output name to resume). If `GEMINI_API_KEY` is set on the machine running the server, the Gemini options appear; the key is never sent to the page.

Safety: it listens on `127.0.0.1` only, requires a random per-launch token (the link printed at start), validates every field, and only serves `.md`/`.pdf` files from the output folder. `--host 0.0.0.0` exposes it to your network: do that only on networks you trust.

## Project layout

```
tube2note/
  cli.py       argument parsing, dispatch          job.py      the resumable download pipeline
  web.py       `serve` local web UI                source.py   yt-dlp listing, subtitles, cache
  tui.py       guided interactive mode             clean.py    transcript cleanup (per-language)
  llm.py       Gemini: transcribe/summarize/translate   whisper.py  offline transcription (optional)
  output.py    files, index, .done/.skip logs      pdf.py      Markdown -> PDF
  config.py    profiles / env / resume info        naming.py   safe names and templates
  ui.py        colors, tables, dashboard           vtt.py      WebVTT parsing
```

Development: `pip install -e ".[dev]" && pytest && ruff check`. The tests run the whole pipeline (and the web UI) offline against a fake yt-dlp in `tests/fake_ydl.py`.

## Configuration precedence

CLI flags > `YT2MD_*` env vars > `--profile` > per-folder `.yt2md.json` > `setup` defaults > builtins.

## NotebookLM limits (verified 2026)

- **Per source: 500,000 words / 200 MB** — identical on every plan.
- Sources per notebook: 50 (Free) → up to 600 (Ultra).
- Rule of thumb: one merged `.md` until 500k words, then `--split-words 400000` into multiple sources.

## FAQ

**HTTP 429?** YouTube throttles sustained subtitle downloads. tube2note slows down automatically (chunks, cooldowns). If throttled hard: stop, wait ~1h (retries extend the ban), resume — progress is saved.

**No subtitles for a video?** Skipped and listed at the end (`## Skipped`) + in `INDEX.md`.

**Big channels?** Use `--max`, `--chunk 25`, longer `--chunk-cooldown`, or run overnight. Resume anytime.

**`yt` command missing/conflicting?** `pip install tube2note` also installs the short `yt` command. If you have the `yt-project` package, the last-installed one wins — uninstall the other or call `tube2note` (full name always works).

**Found a bug / want a feature?** Open an issue — templates for both are included.

## License

MIT — see [LICENSE](LICENSE).
