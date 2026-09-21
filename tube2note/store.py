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
        self.cx = sqlite3.connect(path)
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.executescript(SCHEMA)
        self._new = new

    def close(self):
        try:
            self.cx.close()
        except Exception:
            pass

    def import_sidecars(self, done_log, skip_log):
        """One-time migration from legacy files. Returns True if anything imported."""
        if not self._new:
            return False
        n = 0
        try:
            if os.path.exists(done_log):
                for ln in open(done_log, encoding="utf-8"):
                    vid = ln.strip()
                    if vid:
                        self.mark_done(vid, "", "", 0)
                        n += 1
        except OSError:
            pass
        try:
            if os.path.exists(skip_log):
                import json
                for ln in open(skip_log, encoding="utf-8"):
                    s = ln.strip()
                    if not s:
                        continue
                    try:
                        d = json.loads(s)
                        vid = (VID_RE.search(d.get("url") or "") or [None, d.get("url")])[1]
                        self.mark_skip(vid or d.get("url") or s, d.get("title", ""),
                                       d.get("url", ""), d.get("reason", ""))
                    except ValueError:
                        self.mark_skip(s, "", "", s)
                    n += 1
        except OSError:
            pass
        return n > 0

    def mark_done(self, vid, title, url, words):
        self.cx.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?,?,?,?,?)",
                        (vid, title, url, "done", words, "", time.time()))
        self.cx.commit()

    def mark_skip(self, vid, title, url, reason):
        self.cx.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?,?,?,?,?)",
                        (vid, title, url, "skip", 0, reason, time.time()))
        self.cx.commit()

    def unskip(self, vid):
        self.cx.execute("DELETE FROM videos WHERE id=? AND status='skip'", (vid,))
        self.cx.commit()

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
        self.cx.commit()
