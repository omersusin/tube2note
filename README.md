# tube2note — YouTube → Markdown (and PDF) for NotebookLM

[![PyPI](https://img.shields.io/pypi/v/tube2note)](https://pypi.org/project/tube2note/)
[![CI](https://github.com/omersusin/tube2note/actions/workflows/ci.yml/badge.svg)](https://github.com/omersusin/tube2note/actions)
[![Site](https://img.shields.io/badge/site-tube2note.github.io-blue)](https://omersusin.github.io/tube2note/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Turn a YouTube channel, playlist, or list of videos into **Markdown files** (or PDF) ready to feed NotebookLM / any RAG pipeline. Dependency-light (just `yt-dlp`), resumable, polite to YouTube's rate limits. Terminal, guided mode, local web page, MCP server, or Python API.

🌐 **Site:** https://omersusin.github.io/tube2note/ · 📦 **PyPI:** `pip install tube2note` · 🐙 **Repo:** https://github.com/omersusin/tube2note

## Contents

- [Install](#install) · [Quickstart](#quickstart) · [Guided mode (TUI)](#guided-mode-tui)
- [CLI reference](#cli-reference) · [Watch mode](#watch-mode) · [Search](#search)
- [Web UI](#web-ui) · [Site backend](#site-backend) · [MCP server](#mcp-server) · [Python API](#python-api)
- [Gemini features](#gemini-features) · [Transcript cleaning](#transcript-cleaning) · [PDF](#pdf)
- [Extras](#extras) · [Configuration](#configuration) · [Exit codes](#exit-codes)
- [NotebookLM limits](#notebooklm-limits-verified-2026) · [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout) · [Development](#development) · [Changelog](#changelog) · [FAQ](#faq)

## Install

```bash
pip install tube2note            # needs Python 3.10+, pulls yt-dlp automatically
pip install "tube2note[pdf]"     # + PDF export (fpdf2)
pipx install tube2note           # isolated CLI, recommended on PC/Mac
```

Termux (Android):

```bash
pip install tube2note
tube2note doctor                 # checks yt-dlp, fonts, config, disk
```

From source:

```bash
git clone https://github.com/omersusin/tube2note && cd tube2note
pip install -e ".[dev]"          # + pytest + ruff for development
python3 -m tube2note
```

`pip install tube2note` also installs the short `yt` alias. If you have the `yt-project` package, the last-installed one wins — uninstall the other or always call `tube2note`.

## Quickstart

```bash
tube2note -o notes.md "<playlist_url>" "<video_url>" ...
tube2note -o channel.md --max 200 --layout tree -d ./out "https://www.youtube.com/@SomeChannel/videos"
tube2note status ./out
tube2note watch "https://www.youtube.com/@SomeChannel/videos" -o channel.md --interval 60
tube2note search "transformer" -d ./out
```

## Why not just paste YouTube links into NotebookLM?

- NotebookLM caps YouTube imports (~100 videos) and needs caption files per video.
- tube2note merges everything into sources you control: one file per 500k-word cap, timestamps, chapters, per-video files, resume after interruptions.

## Guided mode (TUI)

Just run `tube2note` (or `tube2note --tui`) with no URLs. It walks you through:

1. **Intro + first-run guide** (HOW TO USE panel with tips, e.g. type `400000` at the split prompt for big files).
2. **Personalize defaults** (optional): folder, layout, languages, timestamps, chunk size/break, name template — saved, or saved as a named `--profile`.
3. **URLs prompt**: validates each URL (invalid ones are rejected with a reason), auto-detects source name, video count, subtitle languages.
4. **Since prompt** (multi-video only): `Only videos since YYYY-MM-DD`.
5. **Settings table** to confirm: output file, folder, layout, languages, max videos, chunking, timestamps, PDF.
6. **Live dashboard**: progress bar + current video + ok/skip/word counts, redrawn in place. `--verbose` switches to scrolling log lines. Optional prompts cover timestamps, clickable links, `.srt`, transcribe/summarize/translate (needs `GEMINI_API_KEY`).

It remembers your last folder and suggests output names from the channel/playlist title.

## CLI reference

```
tube2note [URL ...] [options] | status | setup | doctor | widget | share
          | extras | pdf | watch | search | mcp | serve | serve-api
```

| Flag | Default | What |
|---|---|---|
| `-o, --out` | `tube2note.md` | Output markdown filename |
| `-d, --dir` | config/`.` | Output folder (created if missing) |
| `--layout` | `single` | `single`, `videos`, or `tree` |
| `--lang` | auto | Subtitle priority, e.g. `tr,en` (auto-detected otherwise) |
| `--max` | 100 | Max videos per run (caps listing time too) |
| `--since` | — | Only videos on/after `YYYY-MM-DD` |
| `--timestamps` | off | Keep `[MM:SS]` markers in transcripts |
| `--link-timestamps` / `--no-link-timestamps` | off | Clickable `[MM:SS](youtu.be?t=Ns)` links (implies timestamps; `--no-*` turns off on resume) |
| `--srt` / `--no-srt` | off | Write a `.srt` sidecar per video |
| `--clean / --no-clean` | on | Clean transcripts / keep raw |
| `--clean-level` | `full` | `light` (dedup only) or `full` (fillers + repeats + sentences) |
| `--name-template` | — | Per-video path, e.g. `"{channel}/{title} [{id}]"` (fields: channel, title, id, index, date, lang) |
| `--split-words` | 0 | Auto-split finished file into N-word parts (0 = off) |
| `--pdf` | off | Also write PDF next to the Markdown |
| `--sleep` | 2.0 | Pause between videos (s) |
| `--chunk` | 50 | Long break every N videos |
| `--chunk-cooldown` | 10 min | Break between chunks, in seconds |
| `--fetch-gap` | 10 | Max pause before subtitle fetch (s); `0` = fast mode |
| `--workers` | 1 | Parallel fetch workers 1–4 behind one shared bucket (1 = serial, safest) |
| `--throttle-cooldown` | 1800 | Break after 5 throttles in a row (s) |
| `--proxy` | — | Proxy URL, yt-dlp syntax (`socks5://127.0.0.1:1080`) |
| `--cookies` | — | Netscape `cookies.txt` (logged-in / age-gated content) |
| `--resume-last` | — | Re-run the last saved job (keeps AI/worker flags) |
| `--redo ID[,ID]` | — | Re-process video ID(s): clears cache + old output first |
| `--fresh` | — | Discard previous progress, start over |
| `--profile` | — | Config profile name (or `YT2MD_PROFILE`) |
| `--transcribe` | off | Transcribe captionless videos via Gemini (needs key) |
| `--engine` | `api` | `api` or `local` (your whisper.cpp binary) |
| `--summarize` | off | Per-video Gemini summary (needs key) |
| `--translate LANG` | — | Translate transcript, e.g. `tr` (needs key) |
| `--gemini-model` | gemini-2.5-flash-lite | Model for transcribe/summarize |
| `--yes` | off | Auto-answer yes to extra-download prompts (scripts) |
| `--dry-run` | off | List + estimate only, download nothing |
| `--verbose` | off | Scrolling logs instead of the dashboard |
| `--tui` | — | Force interactive mode |
| `--self-test` | — | Offline self-check (no network) |
| `--version` | — | Print version and exit |

Subcommands: `status [dir] [--json]`, `setup [--advanced]`, `doctor [--proxy]`, `widget` (Termux:Widget one-tap resume), `share` (Termux share-sheet hook), `extras [install|remove] <name> [--yes]`, `pdf <file.md> [...]`, `watch`, `search`, `mcp`, `serve`, `serve-api`.

Pacing model: `--sleep` between videos, `--fetch-gap` before each subtitle fetch, `--chunk`/`--chunk-cooldown` for long breaks, one retry on 429 (hot retries extend bans — the tool stops and waits instead), 30-min cooldown after 5 consecutive throttles. Ban detection covers real YouTube texts (bot-check, 403, IP block), not just 429.

Resume model: `.done` (finished IDs), `.skip` (JSON lines: id/title/url/reason; legacy `|` fallback), `.words` counts. Skip URLs reconcile every run — `youtu.be`, `/shorts/`, `/embed/`, `/live/` forms all understood. Ctrl+C anytime, re-run to continue. Name collisions guarded per-session AND across sessions (frontmatter `video_id` check).

## Watch mode

```bash
tube2note watch URL... -o out.md [--interval MIN] [--max 30] [-d DIR] [--layout L]
                       [--lang LANG] [--timestamps] [--link-timestamps] [--srt]
                       [--no-clean] [--sleep S] [--throttle-cooldown S]
                       [--proxy P] [--cookies F] [--pdf] [--verbose]
tube2note watch --subs subscriptions.yaml [--interval 60]   # many channels, one file each
```

- First run collects everything (up to `--max`); later runs collect **only new videos**. `--subs subscriptions.yaml` watches many channels at once (`- url: ...` + `out:` per entry, no pyyaml needed).
- Seen video IDs live in `~/.cache/tube2note/watch/`. `--interval 0` (default) = check once and exit — ideal for cron / Termux:JobScheduler. `--interval 60` = loop forever (Ctrl+C stops).
- Fatal runs (throttled out, empty result) don't mark anything seen — retried next round.
- `subscriptions.yaml` files load via `tube2note.subs` (Python API).

## Search

```bash
tube2note search "query" -d ./out [--json]
```

Stdlib full-text search over collections (skips `INDEX.md` and split parts). Prints `- [title](file) :: matching line`; `--json` emits structured hits `{file, video_id, title, line}` for scripts.

## Web UI

```bash
tube2note serve                 # http://127.0.0.1:8765, opens browser (Termux: termux-open-url)
tube2note serve -d ~/notes      # output folder (default ./tube2note-out)
tube2note serve --no-open       # just print the link
tube2note serve --port 9000 --token secret   # fixed port + token
tube2note serve --public --allow-host .serveousercontent.com   # public demo (see below)
```

Paste URLs → **Start** → progress → **View / Download**. **Preview** runs `--dry-run`. Each job is a normal `tube2note` subprocess, so resume/layouts/throttling behave exactly like the CLI (re-use an output name to resume). Gemini options appear only if `GEMINI_API_KEY` is set on the server machine — the key is never sent to the page. Safety: binds `127.0.0.1`, random per-launch token, field validation, serves only `.md`/`.pdf` from the output folder. `--host 0.0.0.0` exposes it to your LAN — only on networks you trust.

Public demo recipe (verified): `tube2note serve --public --allow-host .ngrok-free.dev` (no token needed, Gemini options stay hidden) + a tunnel like ngrok or `ssh -R 80:localhost:8765 serveo.net`. `--allow-host` accepts suffixes for rotating tunnel domains. Live right now: https://catalyze-displease-kissable.ngrok-free.dev/ (runs on the dev phone, online while it stays up).

## Site backend

The [site form](https://omersusin.github.io/tube2note/app.html) needs a backend — GitHub Pages is static-only (no Python, no yt-dlp, no secrets, 10s job cap; keys in JS would leak instantly). Free path: deploy `render.yaml` to Render (750h/mo, sleeps; ephemeral FS, `OUT_DIR=/tmp`) or `fly.toml` to Fly.io (512MB for ffmpeg), set `BACKEND_URL` in `docs/app.js`, redeploy Pages. Full runbook: `docs/BACKEND.md`. Backend served by `tube2note serve-api` (FastAPI: `/api/start|stop|state|download` + unauthenticated `/healthz`, token, per-IP queue, max 4 concurrent jobs via `BACKEND_MAX_JOBS`, 50-URL cap, SSRF allow-list for youtube.com/youtu.be only). Local alternative that works today: `tube2note serve` + the PWA shell in `docs/`.

## MCP server

```bash
tube2note mcp
```

Stdio JSON-RPC for Claude/AI assistants. Tools: `download` (url, out, outdir, max, lang, layout, summarize, translate, link_timestamps, srt), `status` (dir), `dry_run` (url, max, lang). Progress output is redirected off the RPC stream. Client config:

```json
{"mcpServers": {"tube2note": {"command": "tube2note", "args": ["mcp"]}}}
```

## Python API

```python
from tube2note import api
code, res = api.collect(["https://www.youtube.com/@SomeChannel/videos"],
                        out="ch.md", overrides={"outdir": "./out"})
videos, hint = api.list_videos(["..."], max_n=50)
suggestion, found = api.language_hint(videos)
```

Plus helpers: `tube2note.links` (clickable `[label](youtu.be/ID?t=Ns)` timestamps), `tube2note.export_srt` (`.srt` per video from cached VTT), `tube2note.subs` (`subscriptions.yaml` loader, no pyyaml). Rule: apps call `api`, never `job` internals.

## Gemini features

Needs a free `GEMINI_API_KEY` env var (transcripts are sent to Google — the tool prints a notice every run; the key always travels in the `x-goog-api-key` header, never in URLs; one retry on 429/5xx).

- `--transcribe`: audio ≤18MB for captionless videos. `--engine local` uses your whisper.cpp binary + tiny model instead (needs ffmpeg for 16kHz WAV).
- `--summarize`: chunk-then-merge per-video summaries (no truncation).
- `--translate LANG`: ID-marked chunks, timing preserved.
- `--gemini-model`: default `gemini-2.5-flash-lite` (2.0-flash is dead/404).

## Transcript cleaning

Default `full`, `--no-clean` disables, `--clean-level light|full`:

- Per-language filler removal (`en/tr/de`; unknown languages keep words — never shreds non-Latin scripts).
- Linear repeat collapse, sentence-per-line, comma repair.
- `light` only dedupes, never deletes words.

## PDF

`pip install "tube2note[pdf]"`, then `--pdf` or `tube2note pdf existing.md [...]`. Unicode TTF preferred (covers Turkish); without a font it folds to ASCII with a warning. `doctor` flags a missing Unicode font (Termux: `/system/fonts/DroidSans.ttf` works).

## Extras

`extras` are heavy/optional, always behind consent (config records enabled ones):

| Extra | What | Size |
|---|---|---|
| `pdf` | PDF export (fpdf2) | ~5MB |
| `whisper` | Offline transcription (whisper.cpp binary + tiny model) | ~75MB |
| `faster-whisper` | Local neural STT — **PC only**, not installable on Termux | ~500MB |

```bash
tube2note extras                    # list + status
tube2note extras install whisper    # prompts once; --yes for scripts
tube2note extras remove pdf
```

## Configuration

Precedence: CLI flags > `YT2MD_*` env vars > `--profile` > per-folder `.yt2md.json` > `setup` defaults > builtins.

| Env var | Sets |
|---|---|
| `YT2MD_OUTDIR` / `YT2MD_LAYOUT` / `YT2MD_LANG` | output folder / layout / languages |
| `YT2MD_CHUNK` / `YT2MD_COOLDOWN_MIN` | chunk size / break minutes |
| `YT2MD_TIMESTAMPS` / `YT2MD_TEMPLATE` | timestamps / name template |
| `YT2MD_CLEAN` / `YT2MD_CLEAN_LEVEL` | cleaning on/off / light/full |
| `YT2MD_PROFILE` | profile name |
| `GEMINI_API_KEY` | AI features |

`setup` writes `~/.config/yt2md/config.json` (`defaults`, `profiles`, `last`, per-profile `last:<name>`, `lastdir`, `extras`). Unknown `--profile` names warn instead of silently falling back. Listing cache (`~/.cache/tube2note/lists/`, 6h, never caches empties) + subtitle cache (`subs/<id>.<lang>.<auto|man>.vtt`) + weekly PyPI check. `XDG_CACHE_HOME` respected.

## Exit codes

`0` = all videos ok · `1` = partial/none (cron-friendly) · `2` = fatal. The web UI treats 0+1 as done.

## NotebookLM limits (verified 2026)

- **Per source: 500,000 words / 200 MB** — identical on every plan.
- Sources per notebook: 50 (Free) → up to 600 (Ultra).
- Rule of thumb: one merged `.md` until 500k words, then `--split-words 400000` into multiple sources.

## Troubleshooting

**HTTP 429 / bot-check / 403?** YouTube throttles sustained subtitle downloads (volume throttle, ASN block, or IP ban). The tool slows down automatically. If throttled hard: stop, wait ~1h — retries extend the ban — then resume; progress is saved. `--proxy`/`--cookies` help logged-in/age-gated content.

**No subtitles for a video?** Skipped and listed at the end (`## Skipped`) + in `INDEX.md`. All subtitle mirrors are tried before skipping. `--transcribe` covers captionless videos.

**Big channels?** `--max 200`, `--chunk 25`, longer `--chunk-cooldown`, `--fetch-gap 0` for speed, or run overnight (`termux-wake-lock` on Android). Resume anytime.

**Disk full?** Writes guard `ENOSPC` and abort cleanly instead of corrupting files.

**`yt` command missing/conflicting?** The short `yt` alias collides with `yt-project` — last-installed wins; full `tube2note` name always works.

**Unknown profile?** A warning names the available profiles — check the spelling.

**PDF shows `?` for Turkish chars?** Missing Unicode font — `doctor` tells you; ASCII fold is a deliberate fallback, not corruption.

## Project layout

```
tube2note/
  cli.py       argument parsing, dispatch          job.py      the resumable download pipeline
  api.py       stable SDK (collect/list/status)    web.py      `serve` local web UI
  server_api.py  FastAPI backend for the site      source.py   yt-dlp listing, subtitles, cache
  tui.py       guided interactive mode             clean.py    transcript cleanup (per-language)
  llm.py       Gemini: transcribe/summarize/translate   whisper.py  offline transcription (optional)
  output.py    files, index, .done/.skip logs      pdf.py      Markdown -> PDF
  config.py    profiles / env / resume info        naming.py   safe names and templates
  ui.py        colors, tables, dashboard           vtt.py      WebVTT parsing
  watch.py     watch mode (new videos only)        mcp.py      MCP server over stdio
  search.py    full-text over collections          links.py    clickable timestamps
  export_srt.py  SRT export                        subs.py     subscriptions.yaml loader
  throttle.py  token bucket + ban detection
```

## Development

```bash
pip install -e ".[dev]" && pytest && ruff check
```

Tests run the whole pipeline (and the web UI) offline against a fake yt-dlp in `tests/fake_ydl.py`. `tube2note --self-test` is a fast offline smoke test. CI runs pytest on 3.10–3.13 + ruff; a `v*` tag auto-publishes to PyPI via trusted publisher (no tokens).

## Changelog

- **0.11.0** — remaining gaps: `watch --subs` subscriptions file, TUI transcribe/summarize/translate prompts, site form AI fields + local-app button, skip-guarded backend test suite (fastapi = server-only by design).
- **0.10.0** — round-2 excavation: search JSON limit fix, site form link/srt + local-app button, BACKEND precision (OUT_DIR, MAX_JOBS, /healthz), 16 adversarial tests, CWD-proof PWA tests, skip-guarded backend suite.
- **0.9.0** — hardening round: watch clean-run-only seen-state, IP-block detection, MCP crash guards, search UTF-8 + limit fix, subs BOM/indent, backend job cap + `?t=` download + `/healthz`, web Timer fix, job try/finally, incomplete-list TTL, VTT poison guard, translate drift warning, cleaner abbreviations + Unicode sentences, link/srt in web UI + TUI + watch, PWA icons + SW registration.
- **0.8.0** — `--link-timestamps` + `--srt` wired into CLI/API/web/MCP (+resume); backend token fail-closed.
- **0.7.0** — site backend (`serve-api`, Render/Fly files), site app form + PWA, clickable-timestamp + SRT libraries, `subscriptions.yaml`, Tauri scaffold.
- **0.6.0** — (rolled into 0.7.0 release) same batch.
- **0.5.0** — audit fixes (subtitle mirror fallthrough, ban-text detection, shorts/youtu.be skip regex, resume keeps AI flags, profile-typo warning, web fd-leak fix) + `tube2note.api` SDK + `search` + Pages site.
- **0.4.0** — `watch` mode, `mcp` server, `extras install/remove`.
- **0.3.0** — parallel fetch fix, VTT header/number fixes, public-mode key guard, clean levels, exit codes, `--redo`/cache/proxy improvements.
- **0.2.x** — package split, `serve` web UI, Gemini transcribe/summarize/translate, TUI, PDF, resume/redo, templates.
- **0.1.x** — initial release, trusted-publisher PyPI, PDF, CI.

## FAQ

**Can I use it directly on the website?** The form needs a backend (see [Site backend](#site-backend)). Without one, use Termux/PC install or local `serve`.

**NotebookLM vs tube2note caps?** NotebookLM takes ~100 YouTube links; tube2note has no video cap — only the 500k-word-per-source limit, handled by `--split-words`.

**Bilingual output?** Not built-in — run once per language with `--lang` + `--translate`.

**Watch vs --resume-last?** Resume re-runs one saved job; watch tracks seen IDs across runs and only fetches new videos.

**Found a bug / want a feature?** Open an issue — templates for both are included.

## License

MIT — see [LICENSE](LICENSE).
