"""Video citation data + APA/MLA/Chicago/BibTeX/RIS. Pure, no deps."""
import re


def _fmt_dur(secs):
    try:
        if secs is None or secs == "":
            return ""
        total = int(float(secs))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        total = 0
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _norm_date(v):
    v = str(v or "").strip()
    if re.fullmatch(r"\d{8}", v):  # yt-dlp upload_date YYYYMMDD
        return f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    return v


def _clean_field(s):
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()


def _q(s):
    return str(s).replace('"', "'")


def cite_data(info=None, **kw):
    """Normalize video metadata into citation fields."""
    data = dict(info) if isinstance(info, dict) else {}
    data.update(kw)
    title = _clean_field(data.get("title") or data.get("video_title") or "Untitled") or "Untitled"
    author = _clean_field(data.get("channel") or data.get("uploader")
                          or data.get("author") or "unknown") or "unknown"
    published = _norm_date(data.get("published") or data.get("upload_date") or data.get("date"))
    year = published[:4] if re.match(r"\d{4}", published) else ""
    url = str(data.get("url") or data.get("webpage_url") or data.get("source") or "").strip()
    vid = str(data.get("video_id") or data.get("id") or "").strip()
    dur = data.get("duration", data.get("duration_secs"))
    return {"title": title, "author": author, "channel": author, "published": published,
            "year": year, "url": url, "video_id": vid, "duration_secs": dur,
            "duration": _fmt_dur(dur)}


def _ensure(d):
    if isinstance(d, dict) and "author" in d and "title" in d:
        dd = dict(d)
        dd["title"] = _clean_field(dd.get("title")) or "Untitled"
        dd["author"] = _clean_field(dd.get("author")) or "unknown"
        return dd
    return cite_data(d if isinstance(d, dict) else {})


def fmt_apa(d):
    d = _ensure(d)
    date = d.get("year") or "n.d."
    s = f"{d['author']}. ({date}). {d['title']} [Video]. YouTube."
    if d.get("duration"):
        s += f" ({d['duration']})."
    if d.get("url"):
        s += f" {d['url']}"
    return s


def fmt_mla(d):
    d = _ensure(d)
    date = d.get("published") or "n.d."
    s = f"\"{_q(d['title'])}.\" YouTube, uploaded by {d['author']}, {date}"
    if d.get("url"):
        s += f", {d['url']}"
    return s + "."


def fmt_chicago(d):
    d = _ensure(d)
    date = d.get("published") or "n.d."
    s = f"{d['author']}. \"{_q(d['title'])}.\" YouTube video"
    if d.get("duration"):
        s += f", {d['duration']}"
    s += f". {date}."
    if d.get("url"):
        s += f" {d['url']}"
    return s


def _bibtex_escape(s):
    s = str(s)
    ph = "\x00"  # stash backslashes so \{ below doesn't re-escape \textbackslash{}
    s = s.replace("\\", ph)
    for c in ("{", "}", "&", "%", "$", "#", "_"):
        s = s.replace(c, "\\" + c)
    s = s.replace("~", r"\~{}").replace("^", r"\^{}")
    return s.replace(ph, r"\textbackslash{}")


def to_bibtex(d, key=None):
    d = _ensure(d)
    key = key or d.get("video_id") or (re.sub(r"\W+", "", d["author"])[:12] + (d.get("year") or "nd")) or "youtube"
    key = re.sub(r"\W+", "", str(key)) or "youtube"
    year = d.get("year") or "n.d."
    fields = [f"  author = {{{_bibtex_escape(d['author'])}}}",
              f"  title = {{{_bibtex_escape(d['title'])}}}", f"  year = {{{year}}}",
              "  howpublished = {YouTube}"]
    if d.get("url"):
        fields.append(f"  url = {{{_bibtex_escape(d['url'])}}}")
    if d.get("duration"):
        fields.append(f"  note = {{{_bibtex_escape(d['duration'])}}}")
    return f"@misc{{{key},\n" + ",\n".join(fields) + ",\n}"


def to_ris(d):
    d = _ensure(d)
    author = _clean_field(d.get("author"))
    title = _clean_field(d.get("title"))
    year = _clean_field(d.get("year"))
    published = _clean_field(d.get("published"))
    url = _clean_field(d.get("url"))
    duration = _clean_field(d.get("duration"))
    lines = ["TY  - ELEC", f"AU  - {author}", f"TI  - {title}"]
    if year:
        lines.append(f"PY  - {year}")
    if published:
        lines.append(f"DA  - {published}")
    if url:
        lines.append(f"UR  - {url}")
    if duration:
        lines.append(f"N1  - Duration: {duration}")
    lines += ["PB  - YouTube", "ER  - "]
    return "\n".join(lines) + "\n"


def citation_block(d):
    d = _ensure(d)
    return ("APA:\n" + fmt_apa(d) + "\n\nMLA:\n" + fmt_mla(d) + "\n\nChicago:\n"
            + fmt_chicago(d) + "\n\nBibTeX:\n" + to_bibtex(d) + "\n\nRIS:\n" + to_ris(d))
