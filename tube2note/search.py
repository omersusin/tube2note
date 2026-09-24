"""Full-text search over collections (stdlib only). `tube2note search QUERY -d DIR`."""
import json
import os
import re


def _split_query(query):
    """Minimal typed syntax: "quoted phrase", -excluded, title:/channel:/id: filters."""
    must, must_not = [], []
    for m in re.finditer(r'-?(?:[A-Za-z_]+:)?"[^"]+"|\S+', query or ""):
        tok = m.group(0)
        neg = tok.startswith("-")
        if neg:
            tok = tok[1:]
        if len(tok) >= 2 and tok.startswith('"') and tok.endswith('"'):
            tok = tok[1:-1]
        fm = re.match(r"(title|channel|video_id|id):(.*)$", tok, re.IGNORECASE)
        if fm:
            f, v = fm.group(1).lower(), fm.group(2).strip()
            if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            v = v.lower()
            if f == "video_id":
                f = "id"
        else:
            f, v = None, tok.lower()
        if not v:
            continue
        (must_not if neg else must).append((f, v))
    return must, must_not


def _matches(line, title, channel, vid, must, must_not):
    targets = {"title": title.lower(), "channel": channel.lower(), "id": vid.lower()}
    targets[None] = f"{line}\n{title}\n{channel}\n{vid}".lower()
    for f, t in must:
        if t not in targets.get(f, ""):
            return False
    for f, t in must_not:
        if t in targets.get(f, ""):
            return False
    return True


def search_collections(query, base=".", as_json=False, limit=50):
    must, must_not = _split_query(query)
    if not must and not must_not:
        print("Usage: tube2note search <text> [-d DIR] [--json]"); return 1
    hits = []
    base = os.path.expanduser(base)
    for root, _, files in os.walk(base):
        if len(hits) >= limit:
            break
        for fn in files:
            if len(hits) >= limit:
                break
            if not fn.endswith(".md") or fn == "INDEX.md":
                continue
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) > 20 * 1024 * 1024:
                    continue
            except OSError:
                continue
            try:
                f = open(p, encoding="utf-8", errors="ignore")
            except OSError:
                continue
            with f:
                cur_vid, cur_title, cur_channel = "", "", ""
                for ln in f:
                    ln = ln.rstrip("\n")
                    m = re.match(r"## \d+\.\s+(.*)", ln)
                    if m:
                        cur_title = m.group(1)[:100]
                    mt = re.match(r"title:\s*(.+?)\s*$", ln)  # tree-layout frontmatter
                    if mt:
                        cur_title = mt.group(1).strip().strip('"')[:100]
                    mc = re.match(r"channel:\s*(.+?)\s*$", ln)
                    if mc:
                        cur_channel = mc.group(1).strip().strip('"')[:100]
                    m2 = re.search(r"Video ID:\s*(\S+)", ln) or re.search(r"video_id:\s*(\S+)", ln)
                    if m2:
                        cur_vid = m2.group(1)
                    if _matches(ln, cur_title, cur_channel, cur_vid, must, must_not):
                        hits.append({"file": os.path.relpath(p, base), "video_id": cur_vid,
                                     "title": cur_title, "line": ln.strip()[:200]})
                        if len(hits) >= limit:
                            break
    if as_json:
        print(json.dumps(hits[:limit], indent=2, ensure_ascii=False))
    else:
        if not hits:
            print(f"No hits for: {query}"); return 0
        for h in hits[:limit]:
            print(f"- [{h['title'] or h['video_id']}]({h['file']}) :: {h['line'][:140]}")
    return 0
