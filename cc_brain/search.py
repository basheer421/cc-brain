"""FTS5 search index over llm-wiki pages."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("cc-brain")


class WikiSearch:
    def __init__(self, db_path, wiki_dir):
        self._db_path = str(db_path)
        self._wiki_dir = Path(wiki_dir)
        self._conn = None

    def _connect(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5("
                "path, title, content, tokenize='trigram')"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS wiki_meta ("
                "path TEXT PRIMARY KEY, mtime REAL, size INTEGER)"
            )
        return self._conn

    def rebuild(self):
        conn = self._connect()
        conn.execute("DELETE FROM wiki_fts")
        conn.execute("DELETE FROM wiki_meta")

        count = 0
        for md in self._wiki_dir.rglob("*.md"):
            rel = str(md.relative_to(self._wiki_dir))
            try:
                text = md.read_text()
                stat = md.stat()
            except OSError:
                continue

            title = ""
            for line in text.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            conn.execute(
                "INSERT INTO wiki_fts (path, title, content) VALUES (?, ?, ?)",
                (rel, title, text),
            )
            conn.execute(
                "INSERT INTO wiki_meta (path, mtime, size) VALUES (?, ?, ?)",
                (rel, stat.st_mtime, stat.st_size),
            )
            count += 1

        conn.commit()
        logger.info("Search index rebuilt: %d pages", count)
        return count

    def update_page(self, rel_path):
        conn = self._connect()
        full = self._wiki_dir / rel_path

        # Remove old entry
        conn.execute("DELETE FROM wiki_fts WHERE path = ?", (rel_path,))
        conn.execute("DELETE FROM wiki_meta WHERE path = ?", (rel_path,))

        if not full.exists():
            conn.commit()
            return

        try:
            text = full.read_text()
            stat = full.stat()
        except OSError:
            conn.commit()
            return

        title = ""
        for line in text.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break

        conn.execute(
            "INSERT INTO wiki_fts (path, title, content) VALUES (?, ?, ?)",
            (rel_path, title, text),
        )
        conn.execute(
            "INSERT INTO wiki_meta (path, mtime, size) VALUES (?, ?, ?)",
            (rel_path, stat.st_mtime, stat.st_size),
        )
        conn.commit()

    def search(self, query, limit=5, scope=None):
        import re

        tokens = re.findall(r"\w+", query)
        if not tokens:
            return []
        query = " OR ".join(f'"{t}"' for t in tokens)
        conn = self._connect()

        scope_filter = ""
        params = [query, limit]
        if scope and scope != "all":
            scope_filter = "AND path LIKE ?"
            params = [query, f"{scope}/%", limit]

        try:
            if scope_filter:
                rows = conn.execute(
                    f"SELECT path, title, snippet(wiki_fts, 2, '>>>', '<<<', '...', 40) as snippet, "
                    f"rank FROM wiki_fts WHERE wiki_fts MATCH ? {scope_filter} "
                    f"ORDER BY rank LIMIT ?",
                    params,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT path, title, snippet(wiki_fts, 2, '>>>', '<<<', '...', 40) as snippet, "
                    "rank FROM wiki_fts WHERE wiki_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    params,
                ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("Search query failed: %s", e)
            return []

        return [
            {
                "path": r["path"],
                "title": r["title"],
                "snippet": r["snippet"],
                "score": round(-r["rank"], 2),
            }
            for r in rows
        ]

    def page_count(self):
        conn = self._connect()
        row = conn.execute("SELECT COUNT(*) FROM wiki_meta").fetchone()
        return row[0] if row else 0

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
