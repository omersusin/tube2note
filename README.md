# yt2md — YouTube → Markdown for NotebookLM

Turn a YouTube channel, playlist, or list of videos into **one Markdown file** (or a folder of them) ready to feed NotebookLM / any RAG pipeline. Single file, zero-install besides `yt-dlp`, resumable, polite to YouTube's rate limits.

```bash
pip install yt-dlp
python3 yt2md.py -o channel.md "https://www.youtube.com/@SomeChannel/videos"
# or guided mode:
python3 yt2md.py
```

## Why not just paste YouTube links into NotebookLM?

- NotebookLM caps YouTube imports (~100 videos) and needs caption files per video.
- yt2md merges everything into Markdown sources you control: one file per 500k-word cap, timestamps, per-video files, resume after interruptions.

## Features

- **Channel / playlist / video URLs** (auto-detected listing, Shorts/tabs handled)
- **Guided TUI**: intro, first-run guide, auto-detected file name / video count / languages, confirm table
- **Anti-throttle engine**: chunks with breaks, jittered pacing, single retry on 429, long cooldown after 5 throttles in a row
- **Resume**: `.done` log — Ctrl+C anytime, continue later; skip log reconciled every run
- **Layouts**: `single` (one .md), `videos` (per-video files + `INDEX.md`), `tree` (`Channel/Video/transcript.md` + `INDEX.md` + YAML frontmatter)
- **Name templates**: `--name-template "{channel}/{title} [{id}]"`
- **Profiles + env**: `--profile X`, `YT2MD_*` vars, per-folder `.yt2md.json` overrides, `setup` wizard
- **NotebookLM-aware**: timestamps option, `--split-words` auto-split under the 500k-word cap
- **Status & dry-run**: `status [dir]` progress table, `--dry-run` estimate before downloading

## Quickstart

```bash
git clone <repo-url> && cd yt2md
pip install yt-dlp
python3 yt2md.py -o notes.md "<playlist_url>" "<video_url>" ...
python3 yt2md.py -o channel.md --max 200 --layout tree -d ./out "https://www.youtube.com/@SomeChannel/videos"
yt2md status ./out
```

## NotebookLM limits (verified 2026)

- **Per source: 500,000 words / 200 MB** — identical on every plan.
- Sources per notebook: 50 (Free) → up to 600 (Ultra).
- Rule of thumb: one merged `.md` until 500k words, then `--split-words 400000` into multiple sources.

## FAQ

**HTTP 429?** YouTube throttles sustained subtitle downloads. yt2md slows down automatically (chunks, cooldowns). If throttled hard: stop, wait ~1h (retries extend the ban), resume — progress is saved.

**No subtitles for a video?** Skipped and listed at the end (`## Skipped`) + in `INDEX.md`.

**Big channels?** Use `--max`, `--chunk 25`, longer `--chunk-cooldown`, or run overnight. Resume anytime.

## License

MIT — see [LICENSE](LICENSE).
