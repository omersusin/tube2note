"""Markdown -> EPUB (stdlib only: zipfile + hand-built XHTML/OPF). No deps."""
import html
import os
import re
import zipfile


def _md_block_to_xhtml(block):
    lines = block.splitlines()
    out, bullets = [], []
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^(#{1,4})\s+(.*)", s)
        if m:
            if bullets:
                out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
                bullets = []
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
        elif s.startswith(("- ", "* ")):
            bullets.append(_inline(s[2:]))
        elif s in ("---", "***"):
            if bullets:
                out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
                bullets = []
            out.append("<hr/>")
        elif s:
            if bullets:
                out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
                bullets = []
            out.append(f"<p>{_inline(s)}</p>")
    if bullets:
        out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
    return "\n".join(out)


def _inline(s):
    s = html.escape(s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def _chapter(title, body):
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>{html.escape(title)}</title></head><body>{body}</body></html>")


def md_to_epub(md_path, epub_path=None):
    """Convert a Markdown collection to EPUB. Returns the epub path."""
    text = open(md_path, encoding="utf-8").read()
    if epub_path is None:
        epub_path = os.path.splitext(md_path)[0] + ".epub"
    parts = re.split(r"(?m)^## ", text)
    head, chapters = parts[0], parts[1:]
    if not chapters:  # no sections: one chapter
        chapters = [head]
        head = ""
    title = "tube2note"
    m = re.search(r"^#\s+(.*)", head, re.M)
    if m:
        title = m.group(1).strip()
    # (assembled below without generators to keep it readable)
    files = {}
    for i, ch in enumerate(chapters):
        first, _, rest = ch.partition("\n")
        ctitle = first.strip()[:80] or f"Part {i + 1}"
        fname = f"ch{i:03d}.xhtml"
        body_src = ch if (i == 0 and not head) else ("## " + ch)
        files[fname] = (_chapter(ctitle, _md_block_to_xhtml(body_src)), ctitle)
    nav = _chapter("Contents", "<h1>Contents</h1><ol>" + "".join(
        f"<li><a href=\"{fn}\">{html.escape(t)}</a></li>" for fn, (_, t) in files.items()) + "</ol>")
    opf_items = "".join(
        f'<item id="ch{i}" href="{fn}" media-type="application/xhtml+xml"/>' for i, fn in enumerate(files))
    opf_spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(len(files)))
    opf = (f'<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" '
           f'version="3.0" unique-identifier="t2n"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f"<dc:title>{html.escape(title)}</dc:title><dc:creator>tube2note</dc:creator>"
           f'<dc:language>en</dc:language></metadata><manifest><item id="nav" href="nav.xhtml" '
           f'media-type="application/xhtml+xml" properties="nav"/>'
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
