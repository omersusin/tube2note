# tube2note backend (Pages can't run the tool — static only)

Pages serves HTML/CSS/JS. No Python, yt-dlp, ffmpeg, secrets, long jobs.
Browsers block YouTube timedtext (CORS + IP-ban). So: Pages hosts docs,
execution runs below. Never put keys in JS.

## Deploy (Render free first, Fly fallback)

Render: Blueprint `render.yaml` → set BACKEND_TOKEN. Free = ephemeral FS
(no disk), sleeps 15min idle, 750h/mo. Transcripts vanish on sleep — download
promptly. Fly: `fly deploy` (512MB shared, force_https). Oracle VPS if you
outgrow both. HF Spaces Docker needs PRO — legacy file kept, don't use free.

Then: set BACKEND_URL in docs/app.js, push → Pages redeploys.

## Local

`tube2note serve -d ~/notes` → open printed 127.0.0.1:8765/?t=... PWA Install
from docs/app.html.
