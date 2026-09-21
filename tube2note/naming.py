"""Safe file names and per-video path templates."""
import re


def _say(*a, **k):
    """Pipe-safe print: stderr when stdout is a data pipe."""
    import sys

    from . import ui as _u
    if _u.PIPE:
        print(*a, file=sys.stderr, flush=True)
    else:
        print(*a, **k)


def slug(s, fallback="tube2note"):
    s = re.sub(r"[^a-z0-9]+", "-", sanitize_filename(s, "").lower()).strip("-")
    return (s[:60] or fallback) + ".md"


WIN_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def sanitize_filename(s, fallback="untitled"):
    """Cross-platform safe single path segment (Windows/macOS/Linux/Android)."""
    tr = str.maketrans("şğüöçıİŞĞÜÖÇ", "sguociisguoc")
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "-", (s or "").translate(tr)).strip(" .")
    if s.lower() in WIN_RESERVED:
        s = "_" + s
    s = (s or fallback).encode("utf-8")[:200].decode("utf-8", "ignore")
    return s or fallback


DEFAULT_TEMPLATES = {
    "single": None,
    "videos": "videos/{title} [{id}]",
    "tree": "{channel}/{title}/transcript",
}


_WARNED_FIELDS = set()


def render_template(tmpl, fields):
    """Fill {field} placeholders; unknown fields become empty (warned once). Sanitize per segment."""
    fields = fields or {}
    unknown = set(re.findall(r"\{(\w+)\}", tmpl or "")) - set(fields)
    new = unknown - _WARNED_FIELDS
    if new:
        _WARNED_FIELDS.update(new)
        _say(f"warning: unknown template field(s): {', '.join(sorted(new))} (left empty)")
    rel = re.sub(r"\{(\w+)\}", lambda m: str(fields.get(m.group(1), "")), tmpl or "")
    segs = [sanitize_filename(p) for p in rel.split("/") if p.strip() and p.strip() != "."]
    rel = "/".join(segs)
    if rel and not rel.lower().endswith(".md"):
        rel += ".md"
    return rel or "untitled.md"
