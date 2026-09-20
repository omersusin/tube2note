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
