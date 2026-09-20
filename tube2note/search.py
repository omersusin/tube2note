"""Full-text search over collections (stdlib only). `tube2note search QUERY -d DIR`."""
import json
import os
import re


def search_collections(query, base=".", as_json=False, limit=50):
    q = (query or "").lower()
    if not q:
        print("Usage: tube2note search <text> [-d DIR] [--json]"); return 1
    hits = []
    base = os.path.expanduser(base)
    for root, _, files in os.walk(base):
        if len(hits) >= limit:
            break
        for fn in files:
            if not fn.endswith(".md") or fn == "INDEX.md" or "_part" in fn:
                continue
            p = os.path.join(root, fn)
            try:
                lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                continue
            cur_vid, cur_title = "", ""
            for ln in lines:
                m = re.match(r"## \d+\.\s+(.*)", ln)
                if m:
                    cur_title = m.group(1)[:100]
                m2 = re.search(r"Video ID:\s*(\S+)", ln)
                if m2:
                    cur_vid = m2.group(1)
                if q in ln.lower():
                    hits.append({"file": os.path.relpath(p, base), "video_id": cur_vid,
                                 "title": cur_title, "line": ln.strip()[:200]})
                    if len(hits) >= limit:
                        break
    if as_json:
        print(json.dumps(hits[:limit], indent=2, ensure_ascii=False))
    else:
        if not hits:
            print("No hits for: " + query); return 0
        for h in hits[:limit]:
            print(f"- [{h['title'] or h['video_id']}]({h['file']}) :: {h['line'][:140]}")
    return 0
