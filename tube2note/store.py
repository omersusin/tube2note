"""SQLite resume store: atomic replacement for .done/.skip/.words sidecars.

One file per collection: <out>.db (WAL mode, commit per video).
Legacy sidecars are auto-imported ONCE (when the db is new) then left alone.
"""
import os
import re
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos(
  id TEXT PRIMARY KEY, title TEXT, url TEXT,
  status TEXT NOT NULL, words INTEGER DEFAULT 0,
  reason TEXT, updated REAL);
CREATE INDEX IF NOT EXISTS idx_status ON videos(status);
CREATE TABLE IF NOT EXISTS hashes(sha TEXT PRIMARY KEY, vid TEXT);
"""

VID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


class Store:
    def __init__(self, path):
        new = not os.path.exists(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        try:
            self.cx = sqlite3.connect(path, timeout=30)
            try:
                self.cx.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            self.cx.executescript(SCHEMA)
        except sqlite3.DatabaseError:
            # corrupt db: start over rather than killing the whole job
            try:
                os.remove(path)
            except OSError:
                pass
            self.cx = sqlite3.connect(path, timeout=30)
            self.cx.executescript(SCHEMA)
            new = True
        self._new = new

    def close(self):
        try:
            self.cx.close()
        except Exception:
            pass

    def _commit(self):
        for _ in range(5):
            try:
                self.cx.commit()
                return
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                    raise
                time.sleep(0.2)
        self._commit()

    def import_sidecars(self, done_log, skip_log):
        """One-time migration from legacy files. Returns True if anything imported."""
        if not self._new:
            return False
        import json
        n = 0
        try:
            if os.path.exists(done_log):
                for ln in open(done_log, encoding="utf-8", errors="replace"):
                    s = ln.strip().lstrip("﻿")
                    if not s:
                        continue
                    m = VID_RE.search(s)
                    vid = m.group(1) if m else s
                    try:
                        self.mark_done(vid, "", "", 0)
                        n += 1
                    except sqlite3.Error:
                        continue
        except OSError:
            pass
        try:
            if os.path.exists(skip_log):
                for ln in open(skip_log, encoding="utf-8", errors="replace"):
                    s = ln.strip().lstrip("﻿")
                    if not s:
                        continue
                    try:
                        d = json.loads(s)
                        if not isinstance(d, dict):
                            raise ValueError("not a dict")
                        vid = (VID_RE.search(d.get("url") or "") or [None, d.get("url")])[1]
                        self.mark_skip(vid or d.get("url") or s, d.get("title", ""),
                                       d.get("url", ""), d.get("reason", ""))
                    except ValueError:
                        if "|" in s:  # legacy pipe format: title | url | reason
                            parts = [p.strip() for p in s.rsplit("|", 2)]
                            url = parts[1] if len(parts) == 3 else ""
                            vid = (VID_RE.search(url) or [None, url])[1]
                            self.mark_skip(vid or s, parts[0] if parts else "",
                                           url, parts[2] if len(parts) == 3 else s)
                        else:
                            self.mark_skip(s, "", "", s)
                    n += 1
        except OSError:
            pass
        return n > 0

    def mark_done(self, vid, title, url, words):
        self.cx.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?,?,?,?,?)",
                        (vid, title, url, "done", words, "", time.time()))
        self._commit()

    def mark_skip(self, vid, title, url, reason):
        self.cx.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?,?,?,?,?)",
                        (vid, title, url, "skip", 0, reason, time.time()))
        self._commit()

    def unskip(self, vid):
        self.cx.execute("DELETE FROM videos WHERE id=? AND status='skip'", (vid,))
        self._commit()

    def done_ids(self):
        return {r[0] for r in self.cx.execute("SELECT id FROM videos WHERE status='done'")}

    def words_map(self):
        return {r[0]: r[1] for r in self.cx.execute("SELECT id, words FROM videos WHERE status='done'")}

    def skips(self):
        """[(id, title, url, reason)] for the Skipped tail + INDEX."""
        return [(r[0], r[1], r[2], r[3]) for r in
                self.cx.execute("SELECT id, title, url, reason FROM videos WHERE status='skip'")]

    def skip_reasons(self):
        return {vid: reason for vid, _, _, reason in self.skips()}

    def counts(self):
        d = self.cx.execute("SELECT COUNT(*) FROM videos WHERE status='done'").fetchone()[0]
        s = self.cx.execute("SELECT COUNT(*) FROM videos WHERE status='skip'").fetchone()[0]
        return d, s

    def hash_owner(self, sha):
        r = self.cx.execute("SELECT vid FROM hashes WHERE sha=?", (sha,)).fetchone()
        return r[0] if r else None

    def note_hash(self, sha, vid):
        self.cx.execute("INSERT OR IGNORE INTO hashes VALUES(?,?)", (sha, vid))
        self._commit()
