"""Clickable timestamps: [label](https://youtu.be/ID?t=Ns). Pure, no deps."""
import re


def fmt_label(secs):
    s = int(secs)
    h, m = s // 3600, s % 3600 // 60
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m:02d}:{s % 60:02d}"


def link_ts(label, vid, secs):
    return f"[{label}](https://youtu.be/{vid}?t={int(secs)}s)"


def chapter_heading(title, vid, secs):
    secs = max(0, secs or 0)
    label = fmt_label(secs)
    if vid:
        return f"## {link_ts(label, vid, secs)} {title}"
    return f"## [{label}] {title}"


def para_text(start, body, vid=None, link=False):
    label = fmt_label(start)
    head = link_ts(label, vid, start) if (link and vid) else f"[{label}]"
    return f"{head} {body}"


def _label_to_secs(label):
    p = [int(x) for x in label.split(":")]
    while len(p) < 3:
        p = [0] + p
    h, m, s = p[-3], p[-2], p[-1]
    return h * 3600 + m * 60 + s


_TS_RE = re.compile(r"\[(\d+:\d{2}(?::\d{2})?)\](?!\()")


def _valid_label(label):
    parts = label.split(":")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return False
    if len(nums) == 2:
        m, s = nums
        return 0 <= s < 60
    if len(nums) == 3:
        h, m, s = nums
        return 0 <= m < 60 and 0 <= s < 60
    return False


def linkify(text, vid):
    """[MM:SS]/[H:MM:SS] markers -> clickable youtu.be links. Idempotent."""
    def _rep(m):
        label = m.group(1)
        if not _valid_label(label):
            return m.group(0)
        return link_ts(label, vid, _label_to_secs(label))
    return _TS_RE.sub(_rep, text)


def thin_markers(text, every):
    """Keep 1 marker per `every` seconds (0 = keep all). Works on plain
    [MM:SS] and linked [label](...?t=Ns) markers."""
    every = int(every or 0)
    if every <= 0:
        return text
    kept = -10 ** 9
    out = []
    pat = re.compile(r"\[(\d+:\d{2}(?::\d{2})?)\](\((?:https?://[^)]+)?\))?")
    pos = 0
    for m in pat.finditer(text):
        secs = _label_to_secs(m.group(1))
        if secs - kept >= every:
            kept = secs
            out.append(text[pos:m.end()])
        else:
            out.append(text[pos:m.start()] + m.group(1))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def to_single_line(text):
    """Obsidian single-line mode: paragraphs joined, markers stay inline."""
    return " ".join(" ".join(p.split()) for p in text.split("\n\n") if p.strip())
