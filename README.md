<img src="docs/icon-192.png" width="64" alt="tube2note logo">

# tube2note — Turn YouTube videos into text

[![PyPI](https://img.shields.io/pypi/v/tube2note)](https://pypi.org/project/tube2note/)
[![Site](https://img.shields.io/badge/site-tube2note.github.io-blue)](https://omersusin.github.io/tube2note/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Turn a YouTube channel, playlist, or videos into **readable text files**. Study, research, or feed them to AI tools like NotebookLM.

🌐 **Site:** https://omersusin.github.io/tube2note/ · 🐙 **Source:** https://github.com/omersusin/tube2note

> **No technical background needed.** Follow the steps in order — your first file will be ready in 10 minutes.

---

## Contents

- [What does it do?](#what-does-it-do)
- [Install: Android (phone)](#install-android-phone)
- [Install: Computer (Windows / Mac / Linux)](#install-computer-windows--mac--linux)
- [First run (step by step)](#first-run-step-by-step)
- [Everyday examples](#everyday-examples)
- [FAQ](#faq)
- [If something breaks](#if-something-breaks)
- [Advanced (optional)](#advanced-optional)

---

## What does it do?

1. You give it a YouTube link (video, channel, or playlist).
2. It downloads what people say in the videos, cleans it up, and makes one readable file.
3. You give that file to NotebookLM as a source and ask questions about the videos.

Example: convert a 200-video course channel into one file, then ask "what was covered in lesson 3?"

For developers: [MCP server](#advanced-optional), [Python API](#advanced-optional), [source code](https://github.com/omersusin/tube2note).

---

## Install: Android (phone)

We use the free **Termux** app to run it on your phone.

### 1. Install Termux

- **Install from F-Droid** (recommended): download F-Droid from [f-droid.org](https://f-droid.org), then install **Termux** from inside F-Droid.
- Don't use the Play Store version — it's outdated.

### 2. Install the needed pieces

Open Termux and type these lines **one by one**, pressing Enter after each:

```bash
pkg update
pkg install python
pip install tube2note
```

Wait for each to finish.

### 3. Check it

```bash
tube2note doctor
```

You'll see a checklist. If all is well, you're done. 🎉

> **Tip:** For long jobs (big channels) running overnight, type `termux-wake-lock` first so the phone doesn't fall asleep.

---

## Install: Computer (Windows / Mac / Linux)

### 1. Install Python (if missing)

- Download from [python.org/downloads](https://www.python.org/downloads/) and install.
- On Windows, tick **"Add python.exe to PATH"** during setup.
- Check: open a terminal (PowerShell/CMD on Windows, Terminal on Mac/Linux) and type `python --version`. You should see a version number.

### 2. Install the program

```bash
pip install tube2note
```

### 3. Check it

```bash
tube2note doctor
```

All good? You're ready. 🎉

---

## First run (step by step)

The easiest way is **guided mode**. Just type:

```bash
tube2note
```

It asks questions, you answer:

1. **Links:** paste your YouTube link (several allowed, separated by spaces).
2. **File name:** pick the output file name (press Enter to accept the suggestion).
3. **Folder:** pick where files are saved.
4. **Settings table:** confirm language, video count, and other settings.
5. **Start:** press Enter and let it work.

Your `.md` file lands in the folder when done. You can watch the progress bar.

> **Interrupted? No problem.** If the internet drops or you close the app, run the same command again — it resumes where it stopped.

---

## Everyday examples

Once comfortable, copy-paste these:

**Download a playlist:**
```bash
tube2note -o notes.md "PASTE_PLAYLIST_LINK"
```

**Download a channel, one file per video:**
```bash
tube2note -o channel.md --layout tree -d ./mynotes "PASTE_CHANNEL_LINK"
```

**Preview first (download nothing):**
```bash
tube2note --dry-run "PASTE_LINK"
```

**Auto-follow new videos:**
```bash
tube2note watch "PASTE_CHANNEL_LINK" -o channel.md --interval 60
```
(First run downloads everything, later runs only fetch new videos.)

**Search inside your downloads:**
```bash
tube2note search "your keyword" -d ./mynotes
```

**Make an EPUB for your e-reader:**
```bash
tube2note epub notes.md
```

**One-tap resume on your phone:** type `tube2note widget` (needs the Termux:Widget app).

---

## FAQ

**How do I give it to NotebookLM?**
Open NotebookLM → "Add source" → upload the `.md` file from your device. One file caps at 500,000 words; for bigger collections run with `--split-words 400000` to auto-split.

**What about videos without subtitles?**
They're skipped and listed under `## Skipped`. Optionally, AI transcription is available (see Advanced).

**It's slow / stuck — what now?**
YouTube sometimes throttles downloads. The program already slows down automatically. If nothing moves: stop it, **wait ~1 hour**, run again — it resumes.

**My device turned off — start over?**
No. Run the same command again, it continues.

**Can I use it on the website?**
The site form needs a separately hosted backend. Easiest is the install above.

**Is it free?**
Yes, completely free and open source (MIT). Optional AI features use Google's free key.

---

## If something breaks

| Problem | Fix |
|---|---|
| `tube2note: command not found` | Install didn't finish. Redo the install steps. |
| Stuck for hours, no progress | Stop, wait 1 hour, run again (YouTube throttled you). |
| `No subtitles` | That video has no captions; it's skipped. If ALL fail, see `--transcribe` (Advanced). |
| Broken Turkish characters (`?` showing) | Run `tube2note doctor`, check the font line. |
| Disk full | Free up space and re-run. Half-written files are safe. |
| Still stuck | [Open an issue](https://github.com/omersusin/tube2note/issues) and describe it. |

---

## Advanced (optional)

For enthusiasts and developers. Not needed for normal use.

**Command-line options** (languages, splitting, cleaning, speed, 40+ flags): run `tube2note --help`. Key ones: `--lang tr,en`, `--timestamps`, `--link-timestamps` (clickable minutes), `--ts-every 30`, `--single-line`, `--srt`, `--txt`, `--pdf`, `--epub`, `--obsidian`, `--split-words`, `--since YYYY-MM-DD`, `--resume-last`, `--redo VIDEO_ID`, `--fresh`, `--proxy`, `--cookies`, `--cookies-from-browser chrome`, `--workers 2`, `--jsonl` (JSON lines for scripts), `-o -` (print transcript to terminal instead of a file), `--bilingual tr` (two languages side by side), `--clean-level light`, `--no-dedupe`, `--engine local`, `--yes`, `--name-template "..."`, `watch --daemon` / `watch --stop` (background watching).

**AI features** (need a free `GEMINI_API_KEY` from [aistudio.google.com](https://aistudio.google.com)): `--transcribe` (transcribe captionless video), `--summarize` (summary per video), `--translate tr`, `--gemini-model`.

**Use from a browser page:** run `tube2note serve` — a page opens on your device to manage jobs.

**Obsidian users:** `--obsidian --layout videos` adds tags + aliases to notes.

**Enrich output:** `--vtt` (.vtt sidecars), `--anki` (flashcards from summaries, needs `--summarize`), `--chapters` (group transcript by video chapters), `--sponsorblock` (skip sponsor segments), `--cite` (APA/MLA/Chicago/BibTeX/RIS citations).

**Automation:** `tube2note status folder --json`, exit codes (0 = ok, 1 = partial, 2 = fatal), `YT2MD_*` env vars, profiles in `~/.config/yt2md/config.json`.

**Developers:** `import tube2note.api` (collect/list/status), `tube2note mcp` (Claude/AI assistant link), `tube2note serve-api` (site backend, FastAPI). Dev setup: `pip install -e ".[dev]" && pytest && ruff check`. Version tags (`v*`) auto-publish to PyPI.

## License

MIT — see [LICENSE](LICENSE).
