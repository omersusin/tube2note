"""Markdown transcript -> clean plain text. Pure, no deps."""
import re

_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_IMG_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


def to_txt(text, meta=None, title="", url="", channel="", published="", duration="", views=""):
    """Strip md chrome, keep readable text + plain MM:SS markers.

    Optional header (title/url/channel/published/duration/views) is
    prepended when given via meta dict or kwargs. ## headings become
    UPPERCASE breaks.
    """
    if isinstance(meta, dict):
        title = title or meta.get("title", "")
        url = url or meta.get("url", "") or meta.get("source", "")
        channel = channel or meta.get("channel", "")
        published = published or meta.get("published", "")
        duration = duration if duration != "" else meta.get("duration", "")
        views = views if views != "" else meta.get("views", "")
    if text is None:
        text = ""
    text = _IMG_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"[\1]", text)
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if s in ("---", "***"):
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            body = m.group(2).strip()
            if len(m.group(1)) == 2:
                out.append("")
                out.append(body.upper())
                out.append("")
            else:
                out.append(body)
            continue
        if s.startswith("- "):
            out.append(s[2:].strip())
            continue
        out.append(s)
    txt = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    def _one(s):
        return " ".join(str(s).split())
    hdr = []
    if title:
        hdr.append(_one(title))
    if url:
        hdr.append(_one(url))
    if channel:
        hdr.append(f"Channel: {_one(channel)}")
    if published:
        hdr.append(f"Published: {_one(published)}")
    if duration != "" and duration is not None:
        try:
            _s = int(duration)
            _dur = f"{_s // 3600}:{(_s % 3600) // 60:02d}:{_s % 60:02d}"
        except (TypeError, ValueError):
            _dur = _one(duration)
        hdr.append(f"Duration: {_dur}")
    if views != "" and views is not None:
        hdr.append(f"Views: {_one(views)}")
    if hdr:
        txt = "\n".join(hdr) + "\n\n---\n\n" + (txt if txt else "")
        return txt if txt.endswith("\n") else txt + "\n"
    return txt + "\n" if txt else ""
