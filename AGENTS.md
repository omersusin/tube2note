# AGENTS.md — tube2note contributor contract

Read this before touching the repo. Short version: verify by execution,
smallest working diff, never break Termux.

## Non-negotiables
- Python stdlib + `yt-dlp` only in core. NEVER add compiled deps
  (no Rust/C extensions — Termux cannot build them). Proven unbuildable:
  curl-cffi, `regex`, faster-whisper/onnxruntime/torch, pydantic v2.
- `ruff check` clean + `pytest -q` green + `tube2note --self-test` ok
  before every commit. No exceptions.
- Pure-python wheels only. `pkg install ruff` works for lint.

## Workflow
- External patches land via chat or `/storage/emulated/0/Download/`: save,
  `git apply --check`, apply subset on overlap, test, commit, push, tag.
- Applier scripts (`*_apply.py`, `.bak*/`) are gitignored — never commit them.
- Version bumps + `v*` tags only when releasing (trusted-publisher workflow
  auto-publishes to PyPI; no tokens anywhere).
- Branch + PR for contributor batches; push straight to main only for
  small maintainer fixes. Delete merged remote branches.
- Commit identity via `-c user.name=omersusin
  -c user.email=86467497+omersusin@users.noreply.github.com` (never global config).

## Code rules
- Ponytail: shortest working diff wins. No speculative abstractions, no
  scaffolding "for later". Delete over add.
- Every fix ships with a test (unit assert + offline pipeline where possible).
- Resume state lives in SQLite (`<out>.db`); legacy sidecars auto-import once.
- Progress/diagnostics must respect pipe mode (`ui.PIPE` → stderr, no files).
- Secrets never in code/docs/JS. Tokens travel in headers, never URLs.
- Public modes (`serve --public`, backend) must never expose Gemini quota/keys.

## Docs discipline
- README is beginner-first (EN), advanced details at the bottom only.
- After every release: regen `docs/VERSION.md`, check badges/links/icons,
  keep `docs/app.html` fields ≡ backend accepted keys. Pages auto-deploys.
- Backend deploys (Render/Fly) are documented in `docs/BACKEND.md`; the
  maintainer owns accounts, agents own files.

## Mobile/desktop
- Flet app = `mobile_main.py` (Flet 1.x API only: `ft.run`, `ft.Button`,
  no `ft.app`/`ElevatedButton`). CI builds the APK; signing via secrets.
- Tauri = `src-tauri/` sidecar around `tube2note serve`; CI builds per tag.
- Brand tokens: charcoal `#161a22`, page `#0d1017`, red `#d92d20`,
  ink `#e8ecf1`, muted `#8b95a5`. Logo source: `docs/brand/render.py`.
