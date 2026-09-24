"""VTT segments -> SRT string. segs: [(start, end, text)]. Pure, no deps."""
import re


def _to_float(s):
    try:
        if s is None or (isinstance(s, str) and s.strip() == ""):
            return 0.0
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _clean_cue(tx):
    if tx is None:
        return ""
    tx = str(tx).replace("\r\n", "\n").replace("\r", "\n")
    tx = tx.replace("-->", "\u2013>")
    tx = re.sub(r"\n[ \t]*\n+", "\n", tx).strip()
    return tx


def _split_text(tx, lim=84):
    out, rest = [], tx.strip()
    while len(rest) > lim:
        cuts = [m.end() for m in re.finditer(r"[.!?;:,]?\s+|[.!?;:,]", rest[: lim + 1])]
        cut = cuts[-1] if cuts and cuts[-1] > lim // 2 else lim
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip() or rest[cut - 1 :].strip()
    out.append(rest)
    return [p for p in out if p]


def clean_cues(triples, lim=84, snap=0.08, merge=0.2):
    """SubtitleEdit-style passes: split long cues, merge tiny gaps, snap ends. Pure."""
    cues, cont = [], []  # cont[i] True -> cue i continues the same original (sibling fragment)
    for st, en, tx in sorted(triples, key=lambda s: (_to_float(s[0]), _to_float(s[1]))):
        st, en, tx = _to_float(st), _to_float(en), _clean_cue(tx)
        if not tx:
            continue
        if en <= st:
            en = st + 2.0
        parts, dur, total = _split_text(tx, lim), en - st, len(tx)
        t = st
        for j, p in enumerate(parts):
            e = en if j + 1 == len(parts) else t + dur * len(p) / total
            cues.append((t, e, p))
            cont.append(j > 0)
            t = e
    merged, mcont = [], []
    for i, c in enumerate(cues):
        if merged and not cont[i] and 1e-9 < c[0] - merged[-1][1] < merge:
            merged[-1] = (merged[-1][0], c[1], merged[-1][2] + " " + c[2])
        else:
            merged.append(c)
            mcont.append(cont[i])
    out = []
    for i, (st, en, tx) in enumerate(merged):
        nxt = merged[i + 1][0] if i + 1 < len(merged) else None
        if nxt is not None and not mcont[i + 1] and en > nxt - snap:
            en = nxt - snap
        if en <= st:
            en = min(st + 0.5, nxt) if nxt is not None and nxt > st else st + 0.5
        out.append((st, en, tx))
    return out


def fmt_srt_ts(s):
    f = _to_float(s)
    try:
        ms = max(0, int(round(f * 1000)))
    except (TypeError, ValueError, OverflowError):
        ms = 0
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    sec, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def segs_to_srt(segs):
    out = []
    segs = clean_cues(list(segs))
    segs = sorted(segs, key=lambda s: (_to_float(s[0]), _to_float(s[1])))
    for i, (st, en, tx) in enumerate(segs, 1):
        st = _to_float(st)
        en = _to_float(en)
        tx = _clean_cue(tx)
        if i < len(segs):
            nxt = _to_float(segs[i][0])
            en = min(en, nxt)
        if en <= st:
            if i < len(segs):
                nxt = _to_float(segs[i][0])
                en = min(st + 2.0, nxt) if nxt > st else st + 0.5
            else:
                en = st + 2.0
        out.append(f"{i}\n{fmt_srt_ts(st)} --> {fmt_srt_ts(en)}\n{tx}\n")
    return "\n".join(out) + ("\n" if out else "")

def fmt_vtt_ts(s):
    f = _to_float(s)
    try:
        ms = max(0, int(round(f * 1000)))
    except (TypeError, ValueError, OverflowError):
        ms = 0
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    sec, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"

def segs_to_vtt(segs):
    out = []
    segs = clean_cues(list(segs))
    segs = sorted(segs, key=lambda s: (_to_float(s[0]), _to_float(s[1])))
    for i, (st, en, tx) in enumerate(segs):
        st = _to_float(st)
        en = _to_float(en)
        tx = _clean_cue(tx)
        if i + 1 < len(segs):
            nxt = _to_float(segs[i + 1][0])
            en = min(en, nxt)
        if en <= st:
            if i + 1 < len(segs):
                nxt = _to_float(segs[i + 1][0])
                en = min(st + 2.0, nxt) if nxt > st else st + 0.5
            else:
                en = st + 2.0
        out.append(f"{fmt_vtt_ts(st)} --> {fmt_vtt_ts(en)}\n{tx}\n")
    return "WEBVTT\n\n" + ("\n".join(out) + ("\n" if out else ""))
