[![version v0.15.0](https://img.shields.io/badge/version-v0.15.0-blue)](https://github.com/omersusin/tube2note/releases/tag/v0.15.0)

## v0.14.1
2aa0b69 0.14.1: wiring gaps (mcp/web/tui epub+)

## v0.14.0
11eb12c 0.14.0: cookies-from-browser

## v0.13.0
75d5795 0.13.0: obsidian notes

## v0.12.0
5a06957 0.12.0: sqlite store, epub, rss fast-path, dedupe
646ac7a README+site: live demo link, public mode accuracy
b86c60d Site: live demo link (public ngrok serve)

## v0.11.0
6ee0c62 0.11.0: watch subs, TUI AI prompts, site AI fields, backend suite

## v0.10.0
65918f3 0.10.0: round-2 excavation (site form, backend docs, 16 adversarial tests)
45e267f Fix ruff in test_upgrade

## v0.9.0
d737c61 0.9.0: agent-excavation hardening (watch/throttle/mcp/search/subs/server/job/cache/vtt/cleaner/completeness)

## v0.8.0
99b8242 0.8.0: link-timestamps/srt wired everywhere, backend token fail-closed, full README
81a501d README deep pass: --fresh/--yes, MCP snippet, env list, serve flags, gemini-model
36260e1 README: exit codes, public demo mode
7bbbe57 README: 0.7.0 features, site link, badges

## v0.7.0
1df0574 0.7.0: backend API, site app, timestamps/SRT libs, subs, tauri scaffold
10b73d0 Merge pull request #2 from omersusin/v060
5026998 v0.6.0+v0.7.0: backend API, site app, timestamps/SRT libs, subs, tauri scaffold
f3b0d29 Pages: allow manual deploy

## v0.5.0
da1487f 0.5.0: audit fixes + api/search/pages
3cc200e Merge pull request #1 from omersusin/v050
e10374d Ruff format: blank lines after imports
2c2cdd4 v0.5.0: audit fixes + api/search/pages

## v0.4.0
4ab1dc7 0.4.0: watch mode, MCP server, extras install/remove
73510db Fix ruff F401: unused imports
4315679 Watch mode, MCP server, extras install/remove + faster-whisper registry
531d9f7 Fix ruff I001: import order in selftest

## v0.3.0
ba6408d 0.3.0: audit fixes (parallel, VTT, public Gemini), clean levels, exit codes, redo/cache/proxy improvements
623e1c7 Allow --allow-host suffix match (.example.com) for rotating tunnel domains

## v0.2.2
35d3d05 0.2.2: fix --workers>1 writing nothing, VTT header/number loss, keep Gemini key off public mode
0ea4127 README: workers, redo, Gemini notice, share hook, json status
55641fa Add --allow-host for tunnel domains (public demos)
c98fe60 Public demo mode (--public) + GitHub Pages site + HF Spaces Dockerfile
fc7f7bb TUI: since prompt only for multi-video, remember last folder

## v0.2.1
f0e68f5 Bump version to 0.2.1
4350a5e Summarize chunk-then-merge (no more 30k cut) + termux share-sheet hook

## v0.2.0
dbe5f83 Split into a package, add `tube2note serve` web UI, add offline pipeline tests
95e9fa2 Fix cleaner corrupting non-English text, keep Gemini key out of URLs, add tests
26bd34d Add --redo, listing cache, status --json, --version, TUI-less redo/resume-last
7ae5efa Add --translate via Gemini (ID-marked chunks, timing preserved) + resume-last support
42942b1 Add --gemini-model selection (default gemini-2.5-flash-lite)
22bf542 Add --summarize via Gemini API (optional, per-video summaries)
41e49cf transcribe: fail fast with clear message when key is missing
1fef1ce Optional Gemini transcription for captionless videos (--transcribe, stdlib only)
0f96ec5 Transcript cleaning pack, default on (--no-clean to disable)
54fb988 Add opt-in parallel fetch (--workers 1-4, shared token bucket) + skip translated subs natively
a1d501a Intro: add HOW TO USE + tips section
0edceee Add --fetch-gap for fast mode (configurable subtitle pacing)
1263af9 Fix audit round 4: cache auto/man keys, profile-aware resume-last (load_config kept runtime keys), doctor proxy, yt-dlp Request (deprecation)
fc40538 Content/RAG quality + reliability: chapters, metadata, subtitle cache, doctor, widget, --since, --proxy/--cookies
ed455cc Fix audit round 3: PDF ASCII-fold fallback, full ENOSPC coverage, strict 429 match

## v0.1.4
c438081 Fix pyproject: valid TOML, classifiers in place
1e1d6a9 Bump version to 0.1.4
033cbcf Fix audit round 2: cross-session collision guard, JSON skip log, early --max cap
006c837 Fix audit findings: throttle detection via yt-dlp messages, proxy/cookies, yt entry point, metadata URLs, template warnings, YAML/frontmatter hardening, ENOSPC guard
6271eb2 Add minimal CI: py_compile + self-test on 3.10-3.13 (council verdict)
ce79f1a Refresh README: pip install, PDF, profiles, precedence

## v0.1.3
972ee0e Bump version to 0.1.3 (PDF export)
a667239 Add PDF export: pdf command, --pdf flag, TUI prompt (optional fpdf2 dep)
e75135c Add bug + feature issue templates

## v0.1.2
f9a7ed6 Bump version to 0.1.2 (0.1.1 filename burned by failed upload)

## v0.1.1
3288377 Bump version to 0.1.1 (trusted publisher test)
4770975 Add trusted-publisher PyPI workflow (tag push publishes)
bb7d4a3 Rename yt2md to tube2note (PyPI/GitHub name free)
bd456a5 Initial release: YouTube to Markdown for NotebookLM
