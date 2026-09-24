"""Markdown -> PDF export (optional fpdf2)."""
import os
import re


def _md_line_kind(line):
    """Classify one markdown line for the PDF renderer (pure, testable)."""
    s = line.rstrip("\n")
    ls = s.lstrip()
    if ls.startswith("#### "):
        return ("h3", ls[5:].strip())
    if ls.startswith("### "):
        return ("h3", ls[4:].strip())
    if ls.startswith("## "):
        return ("h2", ls[3:].strip())
    if ls.startswith("# "):
        return ("h1", ls[2:].strip())
    if s.strip() in ("---", "***"):
        return ("rule", "")
    if s.lstrip().startswith("- "):
        return ("bullet", s.lstrip()[2:].strip())
    if re.match(r"^\s*\d+[.)]\s+\S", s):
        return ("bullet", re.sub(r"^\s*\d+[.)]\s+", "", s).strip())
    if s.strip().startswith("|") and s.strip().endswith("|"):
        return ("row", "  ".join(c.strip() for c in s.strip().strip("|").split("|")))
    return ("para", s.strip())


TR_FOLD = str.maketrans("şŞğĞüÜöÖçÇıİ", "sSgGuUoOcCiI")


def _fold_latin1(s):
    """Best-effort Turkish-preserving fold into latin-1 (for core PDF fonts)."""
    return s.translate(TR_FOLD).encode("latin-1", "replace").decode("latin-1")


CJK_FONTS = ("/system/fonts/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
             "C:/Windows/Fonts/msyh.ttc",
             "/System/Library/Fonts/PingFang.ttc")


def _pdf_font(pdf):
    """Find a system Unicode TTF; returns (font_name, uni_ok)."""
    dejavu = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/data/data/com.termux/files/usr/share/fonts/DejaVuSans.ttf",
        "/system/fonts/DroidSans.ttf",
    ]
    cjk = list(CJK_FONTS) + [
        "/data/data/com.termux/files/usr/share/fonts/TTF/NotoSansCJK-Regular.ttc",
        "/data/data/com.termux/files/usr/share/fonts/NotoSansCJK-Regular.ttc",
    ]
    for p in dejavu + cjk:
        if not os.path.exists(p):
            continue
        try:
            is_ttc = p.lower().endswith(".ttc") or p.lower().endswith(".otc")
            if is_ttc:
                try:
                    pdf.add_font("body", "", p, ttc_index=0)
                except TypeError:
                    pdf.add_font("body", "", p, collection_font_number=0)
            else:
                pdf.add_font("body", "", p)
        except Exception:
            continue
        try:
            if is_ttc:
                try:
                    pdf.add_font("body", "B", p, ttc_index=0)
                except TypeError:
                    pdf.add_font("body", "B", p, collection_font_number=0)
            else:
                b = p.replace(".ttf", "-Bold.ttf").replace(".TTF", "-Bold.ttf")
                pdf.add_font("body", "B", b if os.path.exists(b) else p)
        except Exception:
            pass
        return ("body", True)
    return ("helvetica", False)


def _has_cjk(lines):
    """True if text needs a Unicode font: CJK, Arabic, Hebrew, emoji/symbols."""
    for ln in lines:
        for ch in ln:
            o = ord(ch)
            if (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0x20000 <= o <= 0x2EBEF
                    or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF
                    or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F):
                return True  # CJK / kana / hangul
            if (0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF
                    or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF
                    or 0x0590 <= o <= 0x05FF):
                return True  # Arabic / Hebrew
            if (0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or 0x1F000 <= o <= 0x1FAFF
                    or 0xFE00 <= o <= 0xFE0F or o == 0x200D or 0x2190 <= o <= 0x21FF):
                return True  # emoji / symbols
    return False


def md_to_pdf(md_path, pdf_path=None, meta=None, **kw):
    """Convert our Markdown to PDF. Needs fpdf2 (pip install fpdf2) — optional dep."""
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError:
        raise SystemExit("PDF needs fpdf2: pip install fpdf2  (or pip install tube2note[pdf])")
    combined = dict(meta or {})
    combined.update(kw)
    pdf_path = pdf_path or os.path.splitext(md_path)[0] + ".pdf"

    class _PDF(FPDF):
        _footfont = "helvetica"

        def footer(self):
            try:
                self.set_y(-15)
                try:
                    self.set_font(self._footfont, "", 8)
                except Exception:
                    self.set_font("helvetica", "", 8)
                self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")
            except Exception:
                pass

    pdf = _PDF()
    pdf.alias_nb_pages("{nb}")
    pdf.set_auto_page_break(True, margin=20)
    font, uni = _pdf_font(pdf)
    pdf._footfont = font
    if not uni:
        raise SystemExit("PDF needs a Unicode TTF (DejaVu/Noto/CJK) — none found; "
                         "install dejavu-fonts or set a system font")
    try:
        with open(md_path, encoding="utf-8", errors="replace") as f:
            raw_text = f.read()
    except OSError:
        raise
    except Exception as e:
        raise OSError(f"cannot read {md_path}: {e}")
    lines = raw_text.splitlines()
    title = combined.get("title")
    if not title:
        m = re.search(r"^#\s+(.*)", raw_text, re.M)
        title = m.group(1).strip() if m else os.path.splitext(os.path.basename(md_path))[0]
    author = combined.get("channel", combined.get("creator", combined.get("author", "")))
    if not author:
        m = re.search(r'^channel:\s*"?(.*?)"?\s*$', raw_text, re.M | re.I)
        author = m.group(1).strip().strip('"') if m else "tube2note"
    try:
        pdf.set_title(title if uni else _fold_latin1(title))
        pdf.set_author(author if uni else _fold_latin1(author))
    except Exception:
        pass
    if uni and _has_cjk(lines) and not any(os.path.exists(p) for p in list(CJK_FONTS) + [
            "/data/data/com.termux/files/usr/share/fonts/TTF/NotoSansCJK-Regular.ttc",
            "/data/data/com.termux/files/usr/share/fonts/NotoSansCJK-Regular.ttc"]):
        print("warning: CJK text found but no CJK font installed "
              "(glyphs may render as blank boxes)", flush=True)
    pdf.add_page()
    pdf.set_font(font, size=11)
    # ponytail: fpdf2 2.8 leaves the cursor at the right margin after
    # multi_cell; force LMARGIN or the next line has zero width and crashes.
    def mc(h, t, s=11, st=""):
        try:
            pdf.set_font(font, st, s)
        except Exception:
            pdf.set_font(font, "", s)
        pdf.multi_cell(0, h, t if uni else _fold_latin1(t),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    seen_h2 = False
    def _bm(text, level):
        try:
            pdf.start_section(text if uni else _fold_latin1(text), level=level, strict=False)
        except Exception:
            pass
    for raw in lines:
        if not raw.strip():
            pdf.ln(3)
            continue
        kind, text = _md_line_kind(raw)
        if kind == "h1":
            _bm(text, 0)
            mc(8, text, 16, "B")
            pdf.set_font(font, size=11)
        elif kind == "h2":
            if seen_h2:
                pdf.add_page()
            seen_h2 = True
            _bm(text, 1)
            mc(7, text, 13, "B")
            pdf.set_font(font, size=11)
        elif kind == "h3":
            _bm(text, 2)
            mc(6, text, 12, "B")
            pdf.set_font(font, size=11)
        elif kind == "rule":
            pdf.ln(2)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
        elif kind == "bullet":
            mc(6, "• " + text)
        else:
            mc(6, text)
    tmp = pdf_path + ".tmp"
    pdf.output(tmp)
    os.replace(tmp, pdf_path)
    return pdf_path


def _has_fpdf():
    try:
        import fpdf  # noqa: F401
        return True
    except Exception:
        return False
