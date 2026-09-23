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
