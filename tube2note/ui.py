"""Terminal UI helpers: ANSI colors, panels, tables and the live progress dashboard."""
import os
import re
import shutil
import sys
import time

ANSI_RE = re.compile(r"\033\[[0-9;]*m")


UI_ON = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _len(s):
    return len(ANSI_RE.sub("", s))


def _pad(s, w):
    return s + " " * max(0, w - _len(s))


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if UI_ON else s


def bold(s):
    return _c("1", s)


def green(s):
    return _c("32", s)


def yellow(s):
    return _c("33", s)


def red(s):
    return _c("31", s)


def dim(s):
    return _c("2", s)


def cyan(s):
    return _c("36", s)


def panel(title, lines):
    rows = [title] + list(lines)
    w = max(_len(l) for l in rows)
    edge = "─" * (w + 2)
    out = [f"┌{edge}┐", f"│ {_pad(bold(title), w)} │", f"├{edge}┤"]
    out += [f"│ {_pad(l, w)} │" for l in lines]
    out.append(f"└{edge}┘")
    return "\n".join(out)


def table(headers, rows):
    widths = [_len(h) for h in headers]
    for r in rows:
        for j, c in enumerate(r):
            widths[j] = max(widths[j], _len(str(c)))
    sep = "─┼─".join("─" * w for w in widths)
    head = " │ ".join(_pad(bold(h), w) for h, w in zip(headers, widths))
    out = [head, sep]
    for r in rows:
        out.append(" │ ".join(_pad(str(c), w) for c, w in zip(r, widths)))
    return "\n".join(out)


def bar(frac, width=24):
    frac = max(0.0, min(1.0, frac))
    fill = int(frac * width)
    return f"[{'█' * fill}{'░' * (width - fill)}] {frac * 100:4.0f}%"


def _term_width():
    try:
        return max(40, shutil.get_terminal_size().columns)
    except Exception:
        return 80


def _short(s, w):
    s = str(s)
    return s if len(s) <= w else s[: max(0, w - 1)] + "…"


def _render_dash(done_n, todo_n, title, ok_n, skip_n, words, t0, status=""):
    """Pure: build the 3 dashboard lines (testable without a terminal)."""
    w = _term_width()
    el = (time.time() - t0) / 60
    frac = done_n / todo_n if todo_n else 0
    l1 = _short(f"{bar(frac)} {done_n}/{todo_n} · {words} words · {el:.0f} min", w)
    l2 = _short(f"▶ {title}", w)
    l3 = _short(f"ok {ok_n} · skipped {skip_n}" + (f" · {status}" if status else ""), w)
    return [l1, l2, l3]


_dash_lines = 0  # lines currently drawn (0 = nothing on screen yet)


_VERBOSE = False
PIPE = False  # stdout is a data pipe (tube2note -o -): diagnostics go to stderr, dashboard off


def set_verbose(on):
    """Scrolling log lines (True) instead of the in-place dashboard."""
    global _VERBOSE
    _VERBOSE = bool(on)


def set_pipe(on):
    """Pipe mode: keep stdout clean for transcript data."""
    global PIPE
    PIPE = bool(on)


def dash_update(done_n, todo_n, title, ok_n, skip_n, words, t0, status=""):
    """Redraw the single in-place dashboard (TTY) or plain lines (logs)."""
    global _dash_lines
    if PIPE:
        return
    if _VERBOSE:
        el = (time.time() - t0) / 60
        extra = f" · {status}" if status else ""
        print(f"{done_n}/{todo_n} videos · {words} words · {el:.0f} min{extra}", flush=True)
        return
    if not UI_ON or todo_n <= 0:
        if todo_n > 0 and (done_n % 10 == 0 or done_n >= todo_n):
            print(f"{done_n}/{todo_n} videos · {words} words", flush=True)
        return
    lines = _render_dash(done_n, todo_n, title, ok_n, skip_n, words, t0, status)
    if _dash_lines:
        sys.stdout.write(f"\x1b[{_dash_lines}A")
    for l in lines:
        sys.stdout.write("\r\x1b[K" + l + "\n")
    sys.stdout.flush()
    _dash_lines = len(lines)


def log(msg):
    """Log line that cleanly breaks the live dashboard."""
    global _dash_lines
    if PIPE:
        print(msg, file=sys.stderr, flush=True)
        return
    if _dash_lines and UI_ON:
        sys.stdout.write("\n")
        _dash_lines = 0
    print(msg, flush=True)


def dash_end():
    global _dash_lines
    _dash_lines = 0
