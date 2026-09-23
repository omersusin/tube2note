# UX feedback — first-time student run (2026-09-23, via `python3 -m tube2note`, no `pip install -e .`)

Method: `--help`, `doctor`, `--dry-run` + real `--max 1 --chapters --cite --vtt` on https://www.youtube.com/watch?v=dQw4w9WgXcQ (network OK, no FakeYDL needed), TUI via `printf ... | python3 -m tube2note --tui`.
1. DELIGHT: `--dry-run` resolved the real title + found langs (de-DE, en, en-orig, es-419, ja, pt-BR) + est. time in seconds — perfect preview.
2. DELIGHT: `doctor` one-screen checklist (yt-dlp version, font, disk) gives instant confidence it will work.
3. DELIGHT: TUI rejects non-YouTube URLs instantly with a red message instead of crashing.
4. CONFUSED: `--help` is a 120-line flat wall with no groups and line-wrapped examples — I couldn't scan for `--cite`/`--vtt`.
5. CONFUSED: bare `python3 -m tube2note` under a pipe errors `no URLs`, while README says bare launches guided mode (only true on a tty — needs a `--tui` hint).
6. CONFUSED: `-o /tmp/x.md` dies with a sqlite traceback `unable to open database file` instead of a friendly "can't write there" (Termux /tmp isn't writable).
7. UNFINISHED: `--cite` silently wrote `.bib`/`.ris` and `--vtt` wrote `<out>_<id>.vtt`, but the Done box only mentioned the `.md`.
8. UNFINISHED: `--chapters` on a chapterless video prints nothing — no "no chapters found", so I can't tell if the flag worked.
9. UNFINISHED: TUI advanced options ask for srt/pdf/epub but omit `--chapters`/`--cite`/`--vtt`/`--sponsorblock`, so flags are undiscoverable interactively.
10. BUG: TUI ignored `YT2MD_OUTDIR` and wrote to `/storage/emulated/0/Download/` (lastdir wins) with no warning about the real location.
