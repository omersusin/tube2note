"""Markdown -> EPUB (stdlib only: zipfile + hand-built XHTML/OPF). No deps."""
import html
import os
import re
import zipfile


def _inline(s):
    s = "".join(ch for ch in s if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    return s


def _flush_lists(out, bullets, ordered):
    if bullets:
        out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
        bullets.clear()
    if ordered:
        out.append("<ol>" + "".join(f"<li>{b}</li>" for b in ordered) + "</ol>")
        ordered.clear()


def _md_block_to_xhtml(block):
    lines = block.splitlines()
    out, bullets, ordered, quotes = [], [], [], []
    in_code, code_buf = False, []

    def flush_quote():
        if quotes:
            out.append("<blockquote>" + "".join(f"<p>{q}</p>" for q in quotes) + "</blockquote>")
            quotes.clear()

    for ln in lines:
        if ln.strip().startswith("```"):
            _flush_lists(out, bullets, ordered)
            flush_quote()
            if in_code:
                out.append("<pre><code>" + "\n".join(html.escape(l) for l in code_buf) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(ln)
            continue
        s = ln.strip()
        m = re.match(r"^(#{1,4})\s+(.*)", s)
        if m:
            _flush_lists(out, bullets, ordered)
            flush_quote()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
        elif s in ("---", "***"):
            _flush_lists(out, bullets, ordered)
            flush_quote()
            out.append("<hr/>")
        elif re.match(r"^\d+[.)]\s+\S", s):
            if bullets:
                out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
                bullets.clear()
            flush_quote()
            ordered.append(_inline(re.sub(r"^\d+[.)]\s+", "", s)))
        elif s.startswith(("- ", "* ")):
            if ordered:
                out.append("<ol>" + "".join(f"<li>{b}</li>" for b in ordered) + "</ol>")
                ordered.clear()
            flush_quote()
            bullets.append(_inline(s[2:]))
        elif s.startswith(">"):
            _flush_lists(out, bullets, ordered)
            quotes.append(_inline(s[1:].strip()))
        elif s:
            _flush_lists(out, bullets, ordered)
            flush_quote()
            out.append(f"<p>{_inline(s)}</p>")
        else:
            _flush_lists(out, bullets, ordered)
            flush_quote()
    if in_code:
        out.append("<pre><code>" + "\n".join(html.escape(l) for l in code_buf) + "</code></pre>")
    _flush_lists(out, bullets, ordered)
    flush_quote()
    return "\n".join(out)


def _chapter(title, body):
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>{html.escape(title)}</title></head><body>{body}</body></html>")


def _reading_str(combined):
    rt = combined.get("reading_time", combined.get("reading-time", combined.get("reading")))
    if isinstance(rt, str) and rt.strip():
        return rt.strip()
    mins = combined.get("minutes", combined.get("reading_minutes", combined.get("reading_minutes")))
    if mins is None and isinstance(rt, (int, float)):
        mins = rt
    words = combined.get("words", combined.get("word_count", combined.get("wordcount")))
    if mins is None and isinstance(words, (int, float)):
        mins = max(1, round(words / 200))
    if isinstance(mins, (int, float)):
        return f"~{int(mins)} min read"
    return None


def md_to_epub(md_path, epub_path=None, meta=None, language="en", lang=None, **kw):
    """Convert a Markdown collection to EPUB. Returns the epub path."""
    combined = dict(meta or {})
    combined.update(kw)
    if lang is not None:
        combined["language"] = lang
    elif language != "en" or "language" not in combined:
        combined.setdefault("language", language)
    try:
        with open(md_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        raise
    except Exception as e:
        raise OSError(f"cannot read {md_path}: {e}")
    if epub_path is None:
        epub_path = os.path.splitext(md_path)[0] + ".epub"
    # spine: split on #/##/###/#### chapter headings, keep delimiters
    parts = re.split(r"(?m)(?=^#{1,4} )", text)
    if parts and re.match(r"\s*#{1,4} ", parts[0]):
        head, chapters = "", parts
    else:
        head, chapters = parts[0], parts[1:]
    if not chapters:  # no sections: one chapter
        chapters = [head]
        head = ""
    title = combined.get("title")
    if not title:
        title = "tube2note"
        m = re.search(r"^#\s+(.*)", head, re.M)
        if m:
            title = m.group(1).strip()
    channel = combined.get("channel", combined.get("creator", combined.get("author")))
    if not channel:
        m = re.search(r'^channel:\s*"?(.*?)"?\s*$', text, re.M | re.I)
        channel = m.group(1).strip().strip('"') if m else "tube2note"
    date = combined.get("date", combined.get("published", combined.get("publish_date", "")))
    if not date:
        m = re.search(r"^(?:published|date):\s*(\S+)", text, re.M | re.I)
        date = m.group(1).strip() if m else ""
    url = combined.get("url", combined.get("wurl", combined.get("source",
            combined.get("identifier", combined.get("video_url", "")))))
    if not url:
        m = re.search(r"^- Source:\s*(\S+)", text, re.M)
        if not m:
            m = re.search(r"^source:\s*(\S+)", text, re.M | re.I)
        url = m.group(1).strip() if m else ""
    lang_val = combined.get("language", combined.get("lang", "en")) or "en"
    if lang_val == "en" and language == "en":
        m = re.search(r"^language:\s*([A-Za-z,-]+)", text, re.M | re.I)
        if m:
            lang_val = m.group(1).strip().split(",")[0].strip() or "en"
    ident = url or f"tube2note-{title[:60]}"
    rstr = _reading_str(combined)
    # (assembled below without generators to keep it readable)
    files = {}
    for i, ch in enumerate(chapters):
        m2 = re.search(r"(?m)^#{1,4}\s+(.*)", ch)
        ctitle = (m2.group(1).strip() if m2 else "")[:80] or f"Part {i + 1}"
        fname = f"ch{i:03d}.xhtml"
        body = _md_block_to_xhtml(ch)
        if i == 0 and rstr:
            body = f'<p><em>{html.escape(rstr)}</em></p>\n' + body if body else body
            if not body:
                body = f"<p><em>{html.escape(rstr)}</em></p>"
        files[fname] = (_chapter(ctitle, body), ctitle)
    if rstr and not files:
        files["ch000.xhtml"] = (_chapter(title, f"<p><em>{html.escape(rstr)}</em></p>"), title)
    nav = ('<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" '
           'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body>'
           '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>' + "".join(
               f"<li><a href=\"{fn}\">{html.escape(t)}</a></li>" for fn, (_, t) in files.items())
           + "</ol></nav></body></html>")
    opf_items = "".join(
        f'<item id="ch{i}" href="{fn}" media-type="application/xhtml+xml"/>' for i, fn in enumerate(files))
    opf_spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(len(files)))
    opf = (f'<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" '
           f'version="3.0" unique-identifier="t2n"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="t2n">{html.escape(ident)}</dc:identifier>'
           f"<dc:title>{html.escape(title)}</dc:title><dc:creator>{html.escape(channel)}</dc:creator>"
           + (f"<dc:date>{html.escape(date)}</dc:date>" if date else "")
           + (f"<dc:source>{html.escape(url)}</dc:source>" if url else "")
           + f'<dc:language>{html.escape(lang_val)}</dc:language></metadata><manifest>'
           f'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           f"{opf_items}</manifest><spine>{opf_spine}</spine></package>")
    container = ('<?xml version="1.0" encoding="utf-8"?>\n<container xmlns="urn:oasis:names:tc:opendocument:'
                 'xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
                 'media-type="application/oebps-package+xml"/></rootfiles></container>')
    with zipfile.ZipFile(epub_path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        for fn, (body, _) in files.items():
            z.writestr("OEBPS/" + fn, body)
    return epub_path
