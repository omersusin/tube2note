"""subscriptions.yaml loader for watch v2. Stdlib only (no pyyaml).
Format:
- url: https://www.youtube.com/@Ch/videos
  out: channel.md
  lang: en
  since: 2024-01-01
Lines starting with # ignored. Minimal key: value per indent block.
"""
import os


def load_subs(path="subscriptions.yaml"):
    if not os.path.exists(path):
        return []
    subs, cur = [], {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            ln = raw.rstrip("\n")
            if not ln.strip() or ln.strip().startswith("#"):
                continue
            if ln.startswith("- "):
                if cur.get("url"):
                    subs.append(cur)
                cur = {}
                rest = ln[2:].strip()
                if ":" in rest:
                    k, v = rest.split(":", 1)
                    cur[k.strip()] = v.strip().strip("\"'")
                continue
            if ":" in ln and cur is not None:
                k, v = ln.strip().split(":", 1)
                cur[k.strip()] = v.strip().strip("\"'")
    if cur.get("url"):
        subs.append(cur)
    return [s for s in subs if s.get("url", "").startswith("http")]
