"""Rate-limit helpers: token bucket, throttle detection, countdown."""
import re
import threading
import time

from .ui import UI_ON


def _say(*a, **k):
    """Pipe-safe print: stderr when stdout is a data pipe."""
    import sys

    from . import ui as _u
    if _u.PIPE:
        print(*a, file=sys.stderr, flush=True)
    else:
        print(*a, **k)

VID_RE = r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})"


def _is_throttle(e):
    # yt-dlp wraps HTTP errors in DownloadError/ExtractorError WITHOUT .code,
    # but the message keeps "HTTP Error 429: ..." — check both.
    if getattr(e, "code", None) in (403, 429, 500, 502, 503):
        # 403 alone is not always a ban (private video), so fall through to
        # message check for 403 and require ban phrasing.
        if getattr(e, "code", None) != 403:
            return True
    msg = str(e)
    if re.search(r"\b429\b", msg) is not None or "Too Many Requests" in msg:
        return True
    low = msg.lower()
    if any(k in low for k in (
        "sign in to confirm you",
        "confirm you're not a bot",
        "http error 403",
        "too many requests",
    )):
        return True
    return re.search(r"\bip\b.{0,30}\bblock|\bblock.{0,30}\bip\b", low) is not None


RETRY_AFTER_CAP = 7200  # 2h: a bogus header must never hang forever


def _retry_after_hint(e, default, cap=RETRY_AFTER_CAP):
    """Seconds to wait from a Retry-After hint, or default. Never raises.
    Sources: e.headers / e.response.headers / str(e) `Retry-After: Ns`.
    Non-numeric (HTTP-date, 'soon'), missing, <=0 -> default.
    Absurd (>cap) -> cap. Never shortens below default."""
    raw = None
    for obj in (e, getattr(e, "response", None)):
        h = getattr(obj, "headers", None)
        if h:
            try:
                raw = h.get("Retry-After", h.get("retry-after", None)) if hasattr(h, "get") else None
            except Exception:
                raw = None
            if raw is not None:
                break
    if raw is None:
        m = re.search(r"retry-after\s*[:=]\s*([0-9]+)", str(e or ""), re.IGNORECASE)
        raw = m.group(1) if m else None
    if raw is None:
        return default
    try:
        hint = int(str(raw).strip().split(",")[0].split()[0])
    except (ValueError, TypeError, IndexError):
        return default
    if hint <= 0:
        return default
    return max(default, min(hint, cap))


class Bucket:
    """Thread-safe token bucket: max `rate` timedtext fetches/sec, `capacity` burst."""

    def __init__(self, rate, capacity):
        self.rate, self.capacity = rate, capacity
        self.tokens, self.stamp = capacity, time.monotonic()
        self.lock = threading.Lock()

    def wait(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.stamp) * self.rate)
                self.stamp = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                pause = (1 - self.tokens) / self.rate
            time.sleep(min(pause, 1.0))


def _countdown(secs, label, tick=None):
    # long breaks: plain lines in logs, live status line on TTY via tick()
    if secs <= 0:
        return
    if not UI_ON:
        _say(f"{label}: sleeping ~{secs // 60} min...")
        time.sleep(secs)
        _say(f"{label}: done.")
        return
    end = time.time() + max(1, secs)
    while True:
        left = int(end - time.time())
        if left <= 0:
            break
        if tick:
            tick(left)
        time.sleep(min(5, left))
