"""Transcript cleanup: fillers (per language), repeats, one sentence per line."""
import re

FILLERS = {  # language-specific: a filler in one language is a real word in another ("er" = German "he")
    "en": ("um", "uh", "er", "erm", "ah", "mm", "hmm"),
    "tr": ("ee", "eee", "ıı", "ııı", "hmm", "mm"),
}


_FILLER_CACHE = {}


DUP_MAX_WORDS = 6  # longest repeated phrase we collapse ("you know you know")


ABBR_RE = re.compile(r"\b(Mr|Mrs|Dr|Jr|St)\.")


NUMDOT_RE = re.compile(r"(\d)\.(\d)")


SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZİŞĞÜÖÇ0-9\"“])")


def _filler_re(lang):
    """Compiled filler regex for a language code ('en', 'en-US', ...), or None if we have no list for it."""
    base = (lang or "").split("-")[0].split("_")[0].lower()
    if base not in FILLERS:
        return None
    if base not in _FILLER_CACHE:
        _FILLER_CACHE[base] = re.compile(r"\b(" + "|".join(FILLERS[base]) + r")\b", re.IGNORECASE)
    return _FILLER_CACHE[base]


def _collapse_repeats(body):
    """Collapse immediately repeated words/phrases ("world world", "you know you know") in O(n * DUP_MAX_WORDS)."""
    toks = body.split()
    i, out = 0, []
    while i < len(toks):
        for n in range(min(DUP_MAX_WORDS, (len(toks) - i) // 2), 0, -1):
            gram = [t.lower() for t in toks[i:i + n]]
            j = i + n
            while j + n <= len(toks) and [t.lower() for t in toks[j:j + n]] == gram:
                j += n
            if j > i + n:  # at least one repeat
                out.extend(toks[i:i + n])
                i = j
                break
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)


def _clean_text(text, lang=None, level="full"):
    """Transcript cleanup. Levels: off (passthrough), light (repeats + whitespace
    only, never removes words), full (fillers + repeats + one sentence per line).
    Filler removal is per-language; unknown languages skip fillers (light still applies)."""
    if level == "off":
        return text
    filler_re = _filler_re(lang) if level == "full" else None
    out = []
    for para in text.split("\n\n"):
        tag, body = "", para
        m = re.match(r"(\[\d+:?\d*:\d+\]\s*)", body)
        if m:
            tag, body = m.group(1), body[m.end():]
        if filler_re:
            body = re.sub(r",(\s*,)+", ",", filler_re.sub("", body))  # "this, uh, works" -> "this, works"
        body = _collapse_repeats(body)
        if level == "light":
            body = re.sub(r"\s{2,}", " ", body).strip()
            if body:
                out.append(tag + body)
            continue
        body = ABBR_RE.sub(r"\1<<prd>>", body)
        body = NUMDOT_RE.sub(r"\1<<prd>>\2", body)
        sents = [s.replace("<<prd>>", ".").strip(" ,") for s in SENT_SPLIT_RE.split(body)]
        sents = [re.sub(r"\s{2,}", " ", s).strip() for s in sents if s.strip()]
        if sents:
            out.append(tag + "\n".join(sents))
    return "\n\n".join(out)
