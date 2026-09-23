"""VTT segments -> SRT string. segs: [(start, end, text)]. Pure, no deps."""
def fmt_srt_ts(s):
    ms = max(0, int(round(float(s) * 1000)))
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    sec, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def segs_to_srt(segs):
    out = []
    segs = sorted(segs, key=lambda s: (s[0], s[1]))
    for i, (st, en, tx) in enumerate(segs, 1):
        if i < len(segs):
            en = min(en, segs[i][0])
        if en <= st:
            en = st + 2.0
        out.append(f"{i}\n{fmt_srt_ts(st)} --> {fmt_srt_ts(en)}\n{tx}\n")
    return "\n".join(out) + ("\n" if out else "")
