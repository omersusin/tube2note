"""Output files: front matter, index, .done/.skip logs, splitting, purging."""
import datetime
import glob
import json
import os
import re

from .ui import table


def _purge_jsonl(out, vid):
    """Drop one video's rows from <out>.jsonl (atomic replace)."""
    p = out + ".jsonl"
    if not os.path.exists(p):
        return False
    try:
        lines = open(p, encoding="utf-8").read().splitlines()
    except OSError:
        return False
    kept, dropped = [], False
    for ln in lines:
        try:
            d = json.loads(ln)
            if d.get("video_id") == vid:
                dropped = True
                continue
        except ValueError:
            if vid in ln:  # corrupt line: conservative drop
                dropped = True
                continue
        kept.append(ln)
    if dropped:
        tmp = p + ".tmp"
        try:
            open(tmp, "w", encoding="utf-8").write(("\n".join(kept) + "\n") if kept else "")
            os.replace(tmp, p)
        except OSError:
            return False
    return dropped


def _purge_video(out, root, layout, vid):
    """Forget one video everywhere so --redo reprocesses it cleanly."""
    removed = []
    if _purge_jsonl(out, vid):
        removed.append("jsonl")
    db = out + ".db"
    if os.path.exists(db):
        try:
            from .store import Store
            st = Store(db)
            st.cx.execute("DELETE FROM videos WHERE id=?", (vid,))
            try:
                st.cx.execute("DELETE FROM hashes WHERE vid=?", (vid,))
            except Exception:
                pass
            st.cx.commit()
            st.close()
            removed.append("resume-db")
        except Exception:
            pass
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
    skip_log = out + ".skip"
    if os.path.exists(skip_log):
        try:
            lines = open(skip_log, encoding="utf-8").read().splitlines()
            kept = []
            changed = False
            for ln in lines:
                s = ln.strip()
                if not s:
                    kept.append(ln)
                    continue
                hit = None
                try:
                    d = json.loads(s)
                    u = d.get("url") or ""
                    m = re.search(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)"
                                  r"([A-Za-z0-9_-]{11})", u)
                    hit = (m.group(1) if m else u) == vid
                except ValueError:
                    m = re.search(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)"
                                  r"([A-Za-z0-9_-]{11})", s)
                    hit = (m.group(1) == vid) if m else (vid in s)
                if hit:
                    changed = True
                    continue
                kept.append(ln)
            if changed:
                open(skip_log, "w", encoding="utf-8").write("\n".join(kept) + ("\n" if kept else ""))
                removed.append("skip-log")
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
                    for ext in (".srt", ".txt"):
                        side = os.path.splitext(p)[0] + ext
                        try:
                            if os.path.exists(side):
                                os.remove(side)
                                removed.append("sidecar")
                        except OSError:
                            pass
    base = os.path.splitext(os.path.basename(out))[0]
    for ext in (".srt", ".txt"):
        side = os.path.join(root, f"{base}_{vid}{ext}")
        try:
            if os.path.exists(side):
                os.remove(side)
                removed.append("sidecar")
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


def _fmt_dur(secs):
    """Seconds -> H:MM:SS (ponytail: no zero-pad hour, enough for notes)."""
    try:
        s = int(secs)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        s = 0
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _frontmatter(title, wurl, channel, vid, lg, auto, meta=None, obsidian=False):
    def clean(s):
        s = " ".join(str(s).split()).replace('"', "'").replace("\\", "/")
        return s.strip() or "unknown"
    def qs(s):
        return '"{}"'.format(str(s).replace('"', "'"))
    t = clean(title or vid)
    c = clean(channel or "unknown")
    ch_slug = re.sub(r"[^a-z0-9]+", "-", c.lower()).strip("-") or "unknown"
    today = datetime.date.today().isoformat()
    out = (f"---\ntitle: \"{t}\"\nurl: {qs(wurl)}\nsource: {qs(wurl)}\nchannel: \"{c}\"\n"
           f"videoId: {vid}\nvideo_id: {vid}\nlanguage: {lg}{' (auto)' if auto else ''}\n"
           f"created: {today}\nwatched: {today}\nstatus: watched\n"
           f"tags: [youtube, youtube/channel/{ch_slug}]\n")
    if obsidian:  # Dataview-friendly: tags + alias
        out = out.replace("tags: [youtube, youtube/channel/",
                          "tags: [youtube, transcript, youtube/channel/")
        out += "aliases: [\"{}\"]\n".format(t)
    if meta:
        if meta.get("method"):
            out += f"method: {meta['method']}\n"
        if meta.get("published"):
            out += f"published: {meta['published']}\n"
        if meta.get("duration") is not None:
            out += f"duration: {qs(_fmt_dur(meta['duration']))}\n"
            out += f"duration_secs: {meta['duration']}\n"
        if meta.get("views") is not None:
            out += f"views: {meta['views']}\n"
        if meta.get("channel_url"):
            out += f"channelUrl: {qs(meta['channel_url'])}\n"
        if meta.get("thumbnail"):
            out += f"thumbnailUrl: {qs(meta['thumbnail'])}\n"
        if meta.get("description"):
            out += f"description: \"{clean(meta['description'][:500])}\"\n"
    return out + "---\n\n"


def _video_meta(info):
    """Free metadata from the per-video extract (no extra requests)."""
    ud = info.get("upload_date") or ""
    pub = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}" if len(ud) == 8 else ""
    return {"published": pub, "duration": info.get("duration"),
            "views": info.get("view_count"), "description": info.get("description") or "",
            "channel_url": info.get("channel_url") or info.get("uploader_url") or "",
            "thumbnail": info.get("thumbnail") or ""}


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
            m2 = re.search(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", u or "")
            m[m2.group(1) if m2 else u] = r
    return m


def _write_index(root, videos, completed, words_by_id, reasons):
    """INDEX.md: every video with status, words and per-video file."""
    rows = []
    for v in videos:
        vid = v["id"]
        if vid in completed:
            st = "done"
        elif vid in reasons:
            st = reasons[vid] or "skipped"
        else:
            st = "pending"
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
