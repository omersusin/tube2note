"""Gemini API helpers: transcribe, summarize, translate (stdlib only)."""
import json
import os
import re
import time

from yt_dlp import YoutubeDL

AUDIO_MIMES = {"mp3": "audio/mp3", "wav": "audio/wav", "aac": "audio/aac",
               "ogg": "audio/ogg", "flac": "audio/flac", "m4a": "audio/mp4",
               "webm": "audio/webm"}


AUDIO_MAX_BYTES = 18 * 1024 * 1024


def _download_audio(vid, tmpdir, proxy=None, cookiefile=None):
    """Audio-only download, no ffmpeg: returns (path, ext) or (None, reason)."""
    out = os.path.join(tmpdir, vid + ".%(ext)s")
    opts = {"quiet": True, "no_warnings": True, "skip_download": False,
            "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "outtmpl": out, "socket_timeout": 30}
    if proxy:
        opts["proxy"] = proxy
    if cookiefile:
        opts["cookiefile"] = os.path.expanduser(cookiefile)
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid}"])
    except Exception as e:
        return None, str(e) or type(e).__name__
    for f in os.listdir(tmpdir):
        if f.startswith(vid + "."):
            return os.path.join(tmpdir, f), f.rsplit(".", 1)[-1].lower()
    return None, "audio file not found"


_GEMINI_MODEL = "gemini-2.5-flash-lite"


def _gemini_request(key, payload, model=_GEMINI_MODEL, retries=2):
    """POST to Gemini generateContent over stdlib and return the reply text.

    The API key goes in a header, never the URL (URLs end up in logs, tracebacks and proxies).
    429 / 5xx are retried with backoff, honouring Retry-After.
    """
    import urllib.error
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                try:
                    wait = int(e.headers.get("Retry-After", ""))
                except ValueError:
                    wait = 4 * 2 ** attempt
                time.sleep(min(wait, 60))
                continue
            detail = e.read()[:200].decode("utf-8", "replace")
            raise RuntimeError(f"Gemini API error: HTTP {e.code} {detail}") from None
        except Exception as e:
            raise RuntimeError(f"Gemini API error: {type(e).__name__}: {e}") from None
    try:
        return resp["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Gemini API unexpected response: {str(resp)[:200]}") from None


def _gemini_call(prompt_text, model=_GEMINI_MODEL):
    """Text-only Gemini call. Needs GEMINI_API_KEY."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("this needs GEMINI_API_KEY (free at aistudio.google.com)")
    return _gemini_request(key, {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.0}}, model)


def _gemini_transcribe(audio_bytes, mime, lang="en", model=_GEMINI_MODEL):
    """Send audio to Gemini API, return verbatim transcript. Needs GEMINI_API_KEY."""
    import base64
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("transcribe needs GEMINI_API_KEY (free at aistudio.google.com)")
    return _gemini_request(key, {
        "contents": [{"parts": [
            {"text": f"Transcribe this audio verbatim in {lang}. Output only the transcript text, no commentary."},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio_bytes).decode()}}]}],
        "generationConfig": {"temperature": 0.0}}, model)


def _summary_prompt(text, lang):
    return (f"Summarize the following video transcript (language: {lang}). "
            f"First a 3-sentence overview, then up to 10 bullet key points. "
            f"Reply in {lang}. Transcript:\n\n{text}")


def _translate_chunks(text, target, model, budget=4000):
    """Translate long text in ID-marked chunks so timing/structure survives."""
    paras = [p for p in text.split("\n\n") if p.strip()]
    chunks, cur, n = [], [], 0
    for p in paras:
        if cur and n + len(p) > budget:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += len(p)
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        marked = "\n".join(f"[{i}] {p}" for i, p in enumerate(c))
        prompt = (f"Translate the following to {target}. Keep each [N] marker at the start "
                  f"of its paragraph, translate only the text. Reply with the marked paragraphs only:\n\n{marked}")
        resp = _gemini_call(prompt, model)
        lines, cur = {}, None
        for ln in resp.splitlines():
            m = re.match(r"\[(\d+)\]\s*(.*)", ln.strip())
            if m:
                cur = int(m.group(1))
                lines[cur] = m.group(2)
            elif cur is not None and ln.strip():
                lines[cur] += "\n" + ln.strip()  # model wrapped one paragraph over lines
        out.append("\n\n".join(lines.get(i, c[i]) for i in range(len(c))))
    return "\n\n".join(out)


def _split_words(text, budget=20000):
    """Split text into <=budget-char pieces at paragraph boundaries."""
    chunks, cur, n = [], [], 0
    for p in text.split("\n\n"):
        if not p.strip():
            continue
        if cur and n + len(p) > budget:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += len(p)
    if cur:
        chunks.append(cur)
    return ["\n\n".join(c) for c in chunks] or [text]


def _gemini_summarize(text, lang="en", model=_GEMINI_MODEL):
    parts = _split_words(text)
    if len(parts) == 1:
        return _gemini_call(_summary_prompt(parts[0], lang), model)
    secs = [_gemini_call(_summary_prompt(p, lang), model) for p in parts]
    merge = ("Combine the following section summaries of one video into a single summary: "
             f"a 3-sentence overview, then up to 10 bullet key points. Reply in {lang}.\n\n"
             + "\n\n".join(f"[Part {i}] {s}" for i, s in enumerate(secs)))
    return _gemini_call(merge, model)


def _try_transcribe(vid, lang, tmpdir, model=_GEMINI_MODEL, proxy=None, cookiefile=None):
    """Captionless fallback: audio download + Gemini. Returns (text, note) or (None, reason)."""
    path, ext = _download_audio(vid, tmpdir, proxy, cookiefile)
    if path is None:
        return None, ext
    try:
        if ext not in AUDIO_MIMES:
            return None, f"audio format .{ext} not accepted by API"
        if os.path.getsize(path) > AUDIO_MAX_BYTES:
            return None, "audio too large for API (>18MB)"
        with open(path, "rb") as f:
            text = _gemini_transcribe(f.read(), AUDIO_MIMES[ext], lang, model)
        if len(text) < 50:
            return None, "transcript too short"
        return text, "transcribed via Gemini"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
