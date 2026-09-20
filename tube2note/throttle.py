"""Rate-limit helpers: token bucket, throttle detection, countdown."""
import re
import threading
import time

from .ui import UI_ON


def _is_throttle(e):
    # yt-dlp wraps HTTP errors in DownloadError/ExtractorError WITHOUT .code,
    # but the message keeps "HTTP Error 429: ..." — check both.
    if getattr(e, "code", None) in (429, 500, 502, 503):
        return True
    msg = str(e)
    return re.search(r"\b429\b", msg) is not None or "Too Many Requests" in msg


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
        print(f"{label}: sleeping ~{secs // 60} min...", flush=True)
        time.sleep(secs)
        print(f"{label}: done.", flush=True)
        return
    end = time.time() + max(1, secs)
    while True:
        left = int(end - time.time())
        if left <= 0:
            break
        if tick:
            tick(left)
        time.sleep(min(5, left))
