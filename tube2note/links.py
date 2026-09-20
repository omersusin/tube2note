"""Clickable timestamps: [label](https://youtu.be/ID?t=Ns). Pure, no deps."""
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
