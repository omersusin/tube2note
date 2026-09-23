#!/usr/bin/env python3
"""Sync docs/index.html hero + features from README.md (single source).

Usage: python3 docs/sync_site.py [--check]
  default: rewrite index.html sections, exit 0 (prints changed or clean).
  --check: exit 1 if index.html would change (for CI).

Source blocks in README:
  - tagline: first paragraph after badges (starts with 'YouTube to readable')
  - description: paragraph starting 'Tube2Note is a YouTube'
  - features: the '**Features:** ...' line, split on '·'
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
INDEX = ROOT / "docs" / "index.html"
INSTALL_CMD = "curl -fsSL https://omersusin.github.io/tube2note/install.sh | sh"


def read_src():
    text = README.read_text(encoding="utf-8")
    tagline = re.search(r"^YouTube to readable.*$", text, re.M).group(0)
    desc = re.search(r"^Tube2Note is a YouTube[^\n]+", text, re.M).group(0)
    desc = " ".join(desc.split())
    m = re.search(r"^\*\*Features:\*\* ((?:[^\n]+\n?)+)", text, re.M).group(1)
    feats = [f.strip().rstrip(".") for f in " ".join(m.split("\n")).split("·")]
    return tagline, desc, feats


def feat_card(feat):
    words = feat.split()
    if "/" in words[0]:
        return f'<div class="card"><h3>Exports</h3><p>{feat}</p></div>'
    if len(words) <= 4:
        return f'<div class="card"><h3>{" ".join(words).title()}</h3><p></p></div>'
    if words[0].lower() == "web":
        return f'<div class="card"><h3>Apps & API</h3><p>{" ".join(words[1:])}</p></div>'
    title, rest = words[0], " ".join(words[1:])
    return f'<div class="card"><h3>{title.title()}</h3><p>{rest}</p></div>'


def build(tagline, desc, feats):
    html = INDEX.read_text(encoding="utf-8")
    hero = (
        "<header class=\"hero\">\n"
        "<img src=\"banner.png\" alt=\"tube2note banner\" style=\"max-width:100%;border-radius:12px\">\n"
        f"<p class=\"tag\">{desc}</p>\n"
        "<div class=\"cta\"><a class=\"primary\" href=\"https://github.com/omersusin/tube2note\">GitHub</a>"
        "<a href=\"https://pypi.org/project/tube2note/\">PyPI</a></div>\n"
        f"<pre><code id=\"installcmd\">{INSTALL_CMD}</code> <button onclick=\"navigator.clipboard.writeText(document.getElementById('installcmd').innerText);this.textContent='Copied'\" style=\"cursor:pointer;background:#161a22;border:1px solid #2a3140;border-radius:6px;color:#e8ecf1;padding:.2em .6em\" title=\"Copy\">⧉</button></pre>\n"
        "</header>"
    )
    html = re.sub(r"<header class=\"hero\">.*?</header>", hero, html, flags=re.S)
    cards = "\n".join(feat_card(f) for f in feats)
    html = re.sub(
        r"(<h2>Features</h2>\n<div class=\"grid\">).*?(</div>\n<h2>FAQ</h2>)",
        lambda m: m.group(1) + "\n" + cards + "\n" + m.group(2),
        html,
        flags=re.S,
    )
    _ = tagline  # reserved: short hero line if design wants it back
    return html


def main():
    tagline, desc, feats = read_src()
    new = build(tagline, desc, feats)
    old = INDEX.read_text(encoding="utf-8")
    if "--check" in sys.argv:
        if new != old:
            print("site out of sync: run python3 docs/sync_site.py")
            return 1
        print("site in sync")
        return 0
    if new == old:
        print("site already in sync")
        return 0
    INDEX.write_text(new, encoding="utf-8")
    print("site synced from README")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
