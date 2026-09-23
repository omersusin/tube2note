"""WebVTT parsing and paragraph building."""
import html
import re

TAG_RE = re.compile(r"<(?:/?[A-Za-z][^>]*|\d[^>]*)>")


def _to_secs(t):
    try:
        p = t.strip().split(":")
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        return int(p[0]) * 60 + float(p[1])
    except (ValueError, IndexError, AttributeError):
        return 0.0


def _try_secs(t, prev):
    """Parse a cue start; garbage/prose/negative keeps the previous start."""
    s = (t or "").strip()
    if s.startswith("-"):
        return 0.0
    try:
        p = s.split(":")
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        return int(p[0]) * 60 + float(p[1])
    except (ValueError, IndexError, AttributeError):
        return prev


def _fmt_ts(s):
    s = int(s)
    h, m = s // 3600, s % 3600 // 60
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m:02d}:{s % 60:02d}"


def vtt_segments(vtt: str):
    """Parse VTT into [(start_secs, text)] with back-to-back dupes dropped."""
    lines = vtt.splitlines()
    # everything before the first cue timing line is header: the WEBVTT signature
    # plus YouTube's "Kind: captions" / "Language: en" metadata, never transcript
    in_header = True
    segs, start, saw_cue = [], 0.0, False
    skip_block = False
    for idx, block in enumerate(lines):
        s = block.strip()
        if skip_block:
            if not s:
                skip_block = False
            continue
        if "-->" in s:
            in_header = False
            saw_cue = True
            start = _try_secs(s.split("-->")[0], start)
            continue
        if in_header:
            # header ends at the first cue; WEBVTT may sit on any early line
            if s.lstrip("﻿").strip().upper().startswith("WEBVTT"):
                continue
            if not s:
                continue
            # tolerate leading blank lines: stay in header until a cue appears
            continue
        if not s or s.startswith(("NOTE", "STYLE", "REGION")):
            if s.startswith(("NOTE", "STYLE", "REGION")):
                skip_block = True  # multi-line NOTE/STYLE/REGION blocks
            continue
        if idx + 1 < len(lines) and "-->" in lines[idx + 1]:
            # cue identifier line (numeric or named like cue-99); a spoken
            # number alone ("1999") is real text and has no timing after it
            if s.isdigit() or re.match(r"^[A-Za-z][\w.-]*$", s):
                continue
        s = TAG_RE.sub("", s)
        s = html.unescape(s).replace(" ", " ").strip()
        s = re.sub(r" {2,}", " ", s)
        if s and (not segs or segs[-1][1] != s):  # drop back-to-back duplicates from auto captions
            segs.append((start, s))
    if not saw_cue:
        return []  # not a transcript at all (corrupt cache, error page): never poison output
    return segs


def _para_text(p, ts):
    body = " ".join(t for _, t in p)
    return f"[{_fmt_ts(p[0][0])}] {body}" if ts else body


def _join_paras(segs, ts=False, chapters=None):
    """Group segments into ~20-line paragraphs, or at the video's own chapter boundaries."""
    if chapters:
        ch = sorted(chapters)
        buckets, idx = [[] for _ in ch], 0
        for st, ln in segs:
            while idx + 1 < len(ch) and st >= ch[idx + 1][0]:
                idx += 1
            buckets[idx].append((st, ln))
        out = []
        for (st0, title), b in zip(ch, buckets):
            if not b:
                continue
            out.append(f"### {title}")
            out += [_para_text(b[i:i + 20], ts) for i in range(0, len(b), 20)]
        return "\n\n".join(out)
    paras, buf = [], []
    for i, seg in enumerate(segs, 1):
        buf.append(seg)
        if i % 20 == 0:
            paras.append(buf)
            buf = []
    if buf:
        paras.append(buf)
    return "\n\n".join(_para_text(p, ts) for p in paras)


def vtt_to_text(vtt: str, ts: bool = False) -> str:
    return _join_paras(vtt_segments(vtt), ts)
