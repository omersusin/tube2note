"""Markdown -> PDF export (optional fpdf2)."""
import os


def _md_line_kind(line):
    """Classify one markdown line for the PDF renderer (pure, testable)."""
    s = line.rstrip("\n")
    if s.startswith("## "):
        return ("h2", s[3:].strip())
    if s.startswith("# "):
        return ("h1", s[2:].strip())
    if s.strip() in ("---", "***"):
        return ("rule", "")
    if s.lstrip().startswith("- "):
        return ("bullet", s.lstrip()[2:].strip())
    if s.strip().startswith("|") and s.strip().endswith("|"):
        return ("row", "  ".join(c.strip() for c in s.strip().strip("|").split("|")))
    return ("para", s.strip())


TR_FOLD = str.maketrans("şŞğĞüÜöÖçÇıİ", "sSgGuUoOcCiI")


def _fold_latin1(s):
    """Best-effort Turkish-preserving fold into latin-1 (for core PDF fonts)."""
    return s.translate(TR_FOLD).encode("latin-1", "replace").decode("latin-1")


def _pdf_font(pdf):
    """(font_name, unicode_ok, bold_ok). Prefers a Unicode TTF (Turkish glyphs)."""
    for p in ("/system/fonts/DroidSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/data/data/com.termux/files/usr/share/fonts/DejaVuSans.ttf"):
        if not os.path.exists(p):
            continue
        try:
            pdf.add_font("body", "", p)
        except Exception:
            continue
        bold_ok = False
        try:
            b = p.replace(".ttf", "-Bold.ttf")
            pdf.add_font("body", "B", b if os.path.exists(b) else p)
            bold_ok = True
        except Exception:
            pass
        return "body", True, bold_ok
    return "helvetica", False, True


def md_to_pdf(md_path, pdf_path=None):
    """Convert our Markdown to PDF. Needs fpdf2 (pip install fpdf2) — optional dep."""
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError:
        raise SystemExit("PDF needs fpdf2: pip install fpdf2  (or pip install tube2note[pdf])")
    pdf_path = pdf_path or os.path.splitext(md_path)[0] + ".pdf"
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=20)
    font, uni, bold_ok = _pdf_font(pdf)
    if not uni:
        print("warning: no Unicode font found — non-latin glyphs will be folded to ASCII", flush=True)
    pdf.add_page()
    pdf.set_font(font, size=11)
    # ponytail: fpdf2 2.8 leaves the cursor at the right margin after
    # multi_cell; force LMARGIN or the next line has zero width and crashes.
    def mc(h, t, s=11, st=""):
        pdf.set_font(font, st if (st != "B" or bold_ok) else "", s)
        pdf.multi_cell(0, h, t if uni else _fold_latin1(t),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for raw in open(md_path, encoding="utf-8").read().splitlines():
        if not raw.strip():
            pdf.ln(3)
            continue
        kind, text = _md_line_kind(raw)
        if kind == "h1":
            mc(8, text, 16, "B")
            pdf.set_font(font, size=11)
        elif kind == "h2":
            mc(7, text, 13, "B")
            pdf.set_font(font, size=11)
        elif kind == "rule":
            pdf.ln(2)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
        elif kind == "bullet":
            mc(6, "• " + text)
        else:
            mc(6, text)
    pdf.output(pdf_path)
    return pdf_path


def _has_fpdf():
    try:
        import fpdf  # noqa: F401
        return True
    except Exception:
        return False
