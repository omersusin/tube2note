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


_BAN_PHRASES = (
    "sign in to confirm you",
    "confirm you are not a bot",
    "confirm you are not a robot",
    "confirm you're not a bot",
    "http error 403",
    "http error 429",
    "http error 500",
    "http error 502",
    "http error 503",
    "http error 504",
    "too many requests",
    "service unavailable",
    "internal server error",
    "bad gateway",
    "gateway timeout",
    "rate limit",
    "rate-limit",
    "ratelimit",
    "quota exceeded",
    "quota",
    "slow down",
    "try again later",
    "unusual traffic",
    "captcha",
)
_PRIVATE_WORDS = ("private video", "private ", "this video is private", "deleted",
                  "video unavailable", "copyright", "login required")


def _is_throttle(e):
    # yt-dlp wraps HTTP errors in DownloadError/ExtractorError WITHOUT .code,
    # but the message keeps "HTTP Error 429: ..." — check both.
    try:
        code = int(getattr(e, "code", 0) or 0)
    except (TypeError, ValueError):
        code = 0
    if code in (429, 500, 502, 503, 504):
        return True
    msg = str(e)
    low = msg.lower()
    private = any(k in low for k in _PRIVATE_WORDS)
    ban = any(k in low for k in _BAN_PHRASES)
    if code == 403 or "403" in msg:
        # 403 alone is not always a ban (private video): require ban phrasing,
        # and never when it reads like a private/deleted video.
        return bool(ban and not private)
    if re.search(r"\b429\b", msg):
        # bare "429" (view counts, video ids) is not a ban: need error context.
        return bool(ban or re.search(r"http|error|retr|rate|quota|slow|throttl|ban", low))
    if ban and not private:
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
        try:  # "120.5", "120s"
            hint = int(float(str(raw).strip().split(",")[0].rstrip("s")))
        except (ValueError, TypeError, IndexError):
            return default
    if hint <= 0:
        return default
    return max(default, min(hint, cap))


class Bucket:
    """Thread-safe token bucket: max `rate` timedtext fetches/sec, `capacity` burst."""

    def __init__(self, rate, capacity):
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            rate = 1.0
        try:
            capacity = int(capacity)
        except (TypeError, ValueError):
            capacity = 1
        if rate <= 0:
            rate = 1.0
        if capacity < 1:
            capacity = 1
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
