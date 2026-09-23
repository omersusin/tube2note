"""Markdown transcript -> clean plain text. Pure, no deps."""
import re

_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https://youtu\.be/[^)]+)\)")

def to_txt(text):
    """Strip md chrome, keep readable text + plain MM:SS markers."""
    text = _LINK_RE.sub(r"[\1]", text)
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if s in ("---", "***"):
            continue
        if s.startswith("### "):
            out.append(s[4:].strip())
            continue
        if s.startswith("## "):
            out.append(s[3:].strip())
            continue
        if s.startswith("# "):
            out.append(s[2:].strip())
            continue
        if s.startswith("- "):
            out.append(s[2:].strip())
            continue
        out.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
