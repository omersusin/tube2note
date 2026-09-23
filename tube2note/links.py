"""Clickable timestamps: [label](https://youtu.be/ID?t=Ns). Pure, no deps."""
import re


def fmt_label(secs):
    s = int(secs)
    h, m = s // 3600, s % 3600 // 60
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m:02d}:{s % 60:02d}"


def link_ts(label, vid, secs):
    return f"[{label}](https://youtu.be/{vid}?t={int(secs)}s)"


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


def linkify(text, vid):
    """[MM:SS]/[H:MM:SS] markers -> clickable youtu.be links."""
    return re.sub(r"\[(\d+:\d{2}(?::\d{2})?)\]",
                  lambda m: link_ts(m.group(1), vid, _label_to_secs(m.group(1))), text)


def thin_markers(text, every):
    """Keep 1 marker per `every` seconds (0 = keep all). Works on plain
    [MM:SS] and linked [label](...?t=Ns) markers."""
    every = int(every or 0)
    if every <= 0:
        return text
    kept = -10 ** 9
    out = []
    pat = re.compile(r"\[(\d+:\d{2}(?::\d{2})?)\](\((?:https://youtu\.be/[^)]+)?\))?")
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
    return " ".join(p.strip() for p in text.split("\n\n") if p.strip())
