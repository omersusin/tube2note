"""Summary bullets -> Anki flashcards (CSV/Markdown). Pure, no deps."""
import csv
import io
import re

BULLET_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+(.+?)\s*$")

_SEPS = (" - ", " \u2013 ", " \u2014 ", ": ", " | ", " \u2192 ")


def _split(line):
    for sep in _SEPS:
        if sep in line:
            a, b = line.split(sep, 1)
            a, b = a.strip(), b.strip()
            if a and b:
                return a, b
    return line.strip(), ""


def summary_to_cards(summary, tag="tube2note", max_cards=10, **kw):
    if isinstance(tag, int):  # summary_to_cards(text, 5)
        max_cards, tag = tag, "tube2note"
    max_cards = kw.pop("limit", kw.pop("max", max_cards))
    try:
        want = int(max_cards)
    except (TypeError, ValueError):
        print(f"warning: bad max_cards {max_cards!r}, using 10", flush=True)
        want, max_cards = 10, 10
    else:
        max_cards = min(10, max(0, want))
        if max_cards != want:
            print(f"warning: clamping max_cards {want} to {max_cards}", flush=True)
    cards = []
    for ln in str(summary or "").splitlines():
        m = BULLET_RE.match(ln)
        if not m:
            continue
        front, back = _split(m.group(1))
        if front.strip() or back.strip():
            cards.append((front, back))
        if len(cards) >= max_cards:
            break
    return cards


def _norm(cards):
    out = []
    for c in cards or []:
        if isinstance(c, dict):
            f = c.get("front", c.get("Front", c.get("question", "")))
            b = c.get("back", c.get("Back", c.get("answer", "")))
            t = c.get("tag", c.get("Tag", ""))
            out.append((str(f), str(b), str(t)))
        elif isinstance(c, (list, tuple)):
            f = str(c[0]) if len(c) > 0 else ""
            b = str(c[1]) if len(c) > 1 else ""
            t = str(c[2]) if len(c) > 2 else ""
            out.append((f, b, t))
    return [c for c in out if c[0].strip() or c[1].strip()]


def cards_to_csv(cards, tag="tube2note"):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Front", "Back", "Tag"])
    for f, b, t in _norm(cards):
        w.writerow([f, b, t or tag])
    return buf.getvalue()


def cards_to_md(cards, tag="tube2note"):
    out = ["# Flashcards", ""]
    for i, (f, b, _t) in enumerate(_norm(cards), 1):
        out.append(f"### {i}. {f}")
        out.append("")
        out.append("<details><summary>Answer</summary>")
        out.append("")
        out.append(b)
        out.append("")
        out.append("</details>")
        out.append("")
    return "\n".join(out)
