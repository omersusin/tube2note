# tube2note backend (Pages can't run the tool — static only)

Pages serves HTML/CSS/JS. No Python, yt-dlp, ffmpeg, secrets, long jobs.
Browsers block YouTube timedtext (CORS + IP-ban). So: Pages hosts docs,
execution runs below. Never put keys in JS.

## Deploy (Leapcell free first, Render fallback, Fly last)

Leapcell (Hobby, no card): GitHub connect → Create Service → Python runtime,
build `apt-get update && apt-get install -y ffmpeg && pip install -r
requirements.txt` (needs `fastapi,uvicorn,yt-dlp` in requirements),
start `uvicorn tube2note.server_api:app --host 0.0.0.0 --port 8080`,
env `BACKEND_TOKEN=<secret>`, `OUT_DIR=/tmp/tube2note-out`,
`BACKEND_MAX_JOBS=2`. Serverless: /tmp only, 15-min request cap, idle
suspend — jobs must finish fast and frontend must keep polling /api/state.
Open `*.leapcell.dev/healthz` to verify.

Render: Blueprint `render.yaml` → set BACKEND_TOKEN. Free = ephemeral FS
(no disk), sleeps 15min idle, 750h/mo. Transcripts vanish on sleep — download
promptly. OUT_DIR is `/tmp/tube2note-out`. Healthcheck is unauthenticated
`/healthz` (`/api/*` needs the token). Max 4 concurrent jobs
(`BACKEND_MAX_JOBS`); extra starts get 503. Fly: `fly deploy` (512MB shared,
force_https). Oracle VPS if you outgrow both. HF Spaces Docker needs PRO —
legacy file kept, don't use free.

Then: set BACKEND_URL in docs/app.js, push → Pages redeploys.

## Local

`tube2note serve -d ~/notes` → open printed 127.0.0.1:8765/?t=... PWA Install
from docs/app.html.
