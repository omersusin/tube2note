"""Output files: front matter, index, .done/.skip logs, splitting, purging."""
import glob
import json
import os
import re

from .ui import table


def _purge_video(out, root, layout, vid):
    """Forget one video everywhere so --redo reprocesses it cleanly."""
    removed = []
    done_log = out + ".done"
    if os.path.exists(done_log):
        try:
            lines = open(done_log, encoding="utf-8").read().splitlines()
            kept = [ln for ln in lines if ln.strip() != vid]
            if len(kept) != len(lines):
                open(done_log, "w", encoding="utf-8").write("\n".join(kept) + ("\n" if kept else ""))
                removed.append("done-log")
        except OSError:
            pass
    cdir = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                        "tube2note", "subs")
    for p in glob.glob(os.path.join(cdir, f"{vid}.*.vtt")):
        try:
            os.remove(p)
            removed.append("cache")
        except OSError:
            pass
    if os.path.exists(out):
        try:
            raw = open(out, encoding="utf-8").read()
            parts = raw.split("---\n\n")
            kept = [parts[0]] + [p for p in parts[1:] if f"Video ID: {vid}\n" not in p]
            if len(kept) != len(parts):
                open(out, "w", encoding="utf-8").write("---\n\n".join(kept))
                removed.append("combined-md")
        except OSError:
            pass
    if layout != "single":
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".md") or fn == "INDEX.md":
                    continue
                p = os.path.join(dirpath, fn)
                if _existing_vid(p) == vid:
                    try:
                        os.remove(p)
                        removed.append("per-video-file")
                    except OSError:
                        pass
    return removed


def split_output(out, budget):
    """Split a finished md into <=budget-word parts at video boundaries. Returns part paths."""
    raw = open(out, encoding="utf-8").read()
    head, sep, body = raw.partition("---\n\n")
    head = head + sep if sep else ""
    sections = [s for s in body.split("---\n\n") if s.strip()]
    base, ext = os.path.splitext(out)
    parts, cur, curw, idx = [], [], 0, 0
    for s in sections:
        w = len(s.split())
        if cur and curw + w > budget:
            parts.append((idx + 1, cur))
            cur, curw, idx = [], 0, idx + 1
        cur.append(s)
        curw += w
    if cur:
        parts.append((idx + 1, cur))
    if len(parts) <= 1:
        return []
    paths = []
    for i, secs in parts:
        lines = head.split("\n")
        if lines:
            lines[0] += f" (part {i}/{len(parts)})"
        p = f"{base}_part{i:02d}{ext}"
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("---\n\n".join(secs)) + "---\n")
        paths.append(p)
    return paths


def _frontmatter(title, wurl, channel, vid, lg, auto, meta=None):
    def clean(s):
        s = " ".join(str(s).split()).replace('"', "'").replace("\\", "/")
        return s.lstrip("-?:,{}[]&*!|>#%@` ").strip() or "unknown"
    t = clean(title or vid)
    c = clean(channel or "unknown")
    out = (f"---\ntitle: \"{t}\"\nsource: {wurl}\nchannel: \"{c}\"\n"
           f"video_id: {vid}\nlanguage: {lg}{' (auto)' if auto else ''}\n")
    if meta:
        if meta.get("method"):
            out += f"method: {meta['method']}\n"
        if meta.get("published"):
            out += f"published: {meta['published']}\n"
        if meta.get("duration") is not None:
            out += f"duration_secs: {meta['duration']}\n"
        if meta.get("views") is not None:
            out += f"views: {meta['views']}\n"
        if meta.get("description"):
            out += f"description: \"{clean(meta['description'][:500])}\"\n"
    return out + "---\n\n"


def _video_meta(info):
    """Free metadata from the per-video extract (no extra requests)."""
    ud = info.get("upload_date") or ""
    pub = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}" if len(ud) == 8 else ""
    return {"published": pub, "duration": info.get("duration"),
            "views": info.get("view_count"), "description": info.get("description") or ""}


def _existing_vid(path):
    """Read video_id from an existing per-video file's frontmatter (None if unknown)."""
    try:
        with open(path, encoding="utf-8") as f:
            for i, ln in enumerate(f):
                if i > 12:
                    break
                m = re.match(r"video_id:\s*(\S+)", ln)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _unique_path(vp, vid, used):
    """Disambiguate slug collisions: second same-named file gets _<video_id>."""
    if vp in used:
        base, ext = os.path.splitext(vp)
        vp = f"{base}_{vid}{ext}"
    used.add(vp)
    return vp


def _count_lines(path):
    try:
        return sum(1 for ln in open(path, encoding="utf-8") if ln.strip())
    except OSError:
        return 0


def _skip_map(skip_log):
    """Parse skip lines into {video_id_or_url: reason}. JSON first, legacy 'a | b | c' via right-split."""
    m = {}
    try:
        lines = open(skip_log, encoding="utf-8")
    except OSError:
        return m
    with lines:
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            try:
                d = json.loads(s)
                t, u, r = d.get("title", ""), d.get("url", ""), d.get("reason", "")
            except (ValueError, AttributeError):
                parts = [p.strip() for p in s.rsplit(" | ", 2)]
                if len(parts) != 3:
                    continue
                t, u, r = parts
            m2 = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", u or "")
            m[m2.group(1) if m2 else u] = r
    return m


def _write_index(root, videos, completed, words_by_id, skip_log):
    """INDEX.md: every video with status, words and per-video file."""
    reasons = _skip_map(skip_log)
    rows = []
    for v in videos:
        vid = v["id"]
        st = "done" if vid in completed else reasons.get(vid, "pending")
        rows.append([v.get("title") or vid, st, str(words_by_id.get(vid, "-"))])
    with open(os.path.join(root, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write(f"# Index\n\n- Videos: {len(videos)}\n- Done: {len(completed)}\n\n")
        f.write(table(["Title", "Status", "Words"], rows))


COLLECTION_KEYS = ("layout", "lang", "timestamps", "chunk", "chunk_cooldown_min")


def _collection_override(root):
    """Per-collection .yt2md.json overrides (safe subset only)."""
    try:
        data = json.load(open(os.path.join(root, ".yt2md.json"), encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in COLLECTION_KEYS if k in data}
