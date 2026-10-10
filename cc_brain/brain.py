"""brain.db — the v3 memory store.

facts     : atomic semantic memory (one claim each), bi-temporal via superseded_by
episodes  : chunks of session summaries, time-indexed (episodic memory)
docs      : chunks of hand-written wiki pages (skills/)
aliases   : entity alias -> canonical, used for query expansion

Retrieval = BM25 (FTS5 porter) ∪ dense (Ollama embeddings) fused with RRF, then
scaled by recency × importance × project match (Generative Agents style).
"""

import logging
import math
import re
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from .embed import Embedder, from_blob, to_blob
from .episodes import parse_summary

logger = logging.getLogger("cc-brain")

KINDS = ("fact", "pitfall", "decision", "preference", "correction", "procedure", "person", "note")
RRF_K = 60
POOL = 50
DAY = 86400.0

STOP = set("""a an and are as at be but by for from has have how i if in into is it its of on or
that the their then there this to was were what when where which who why will with you your
did do does done we me my our can could should would""".split())

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fact',
    project TEXT NOT NULL DEFAULT 'global',
    entities TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    updated REAL NOT NULL,
    last_seen REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    importance INTEGER NOT NULL DEFAULT 2,
    superseded_by INTEGER,
    original TEXT,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS facts_live ON facts(superseded_by, project);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(text, project, entities, tokenize='porter unicode61');

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    file TEXT NOT NULL,
    session TEXT, project TEXT, cwd TEXT, title TEXT,
    day TEXT, ts REAL, section TEXT, text TEXT,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS episodes_file ON episodes(file);
CREATE INDEX IF NOT EXISTS episodes_day ON episodes(day, project);
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(text, project, section, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS episode_files (file TEXT PRIMARY KEY, mtime REAL);

CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY, path TEXT, section TEXT, text TEXT, embedding BLOB
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(path, section, text, tokenize='porter unicode61');

CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, canonical TEXT NOT NULL);
"""


def norm_tokens(text):
    return {t for t in re.findall(r"\w+", (text or "").lower()) if t not in STOP and len(t) > 1}


def fact_doc(text, project="", entities=""):
    """What gets embedded: context-bearing (sub-bullets lose their page/section context otherwise)."""
    ctx = " / ".join(p for p in (project if project != "global" else "", entities) if p)
    return f"[{ctx}] {text}" if ctx else text


def jaccard(a, b):
    a, b = norm_tokens(a), norm_tokens(b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Brain:
    def __init__(self, db_path, config=None, embedder=None):
        self.path = str(Path(db_path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.embedder = embedder if embedder is not None else Embedder(config)
        self._lock = threading.RLock()
        self._mat_cache = {}

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------------ query parsing

    def aliases(self):
        return {r["alias"]: r["canonical"] for r in self.conn.execute("SELECT * FROM aliases")}

    def add_alias(self, alias, canonical):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO aliases VALUES (?, ?)", (alias.lower(), canonical.lower()))
            self.conn.commit()

    def _expand(self, query):
        """Tokens + every alias in the same alias group (Bob -> robert, bob@acme...)."""
        tokens = [t for t in re.findall(r"\w+", query.lower()) if t not in STOP]
        amap = self.aliases()
        groups = {}
        for a, c in amap.items():
            groups.setdefault(c, {c}).add(a)
        out = []
        for t in tokens:
            out.append(t)
            canon = amap.get(t, t)
            out.extend(sorted(groups.get(canon, {canon}) - {t}))
        seen, uniq = set(), []
        for t in out:
            for part in re.findall(r"\w+", t):
                if part not in seen:
                    seen.add(part)
                    uniq.append(part)
        return uniq

    def _match(self, query):
        tokens = self._expand(query)
        return " OR ".join(f'"{t}"' for t in tokens) if tokens else None

    # ------------------------------------------------------------------ facts: write

    def _fts_put(self, fid, text, project, entities):
        self.conn.execute("DELETE FROM facts_fts WHERE rowid = ?", (fid,))
        self.conn.execute(
            "INSERT INTO facts_fts(rowid, text, project, entities) VALUES (?, ?, ?, ?)",
            (fid, text, project, entities),
        )

    def nearest_facts(self, text, project=None, limit=8):
        """Hybrid neighbours of `text` among live facts (for dedup / memory ops)."""
        return self.recall(text, project=project, limit=limit, touch=False, raw=True)

    def add_fact(self, text, kind="fact", project="global", entities="", source="",
                 importance=2, dedup=True, embed=True, ts=None):
        """Insert a fact. Deterministic dedup: near-identical live fact -> touch it instead.
        Returns (id, op) where op in {'ADD', 'NOOP'}."""
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if not text:
            return None, "SKIP"
        kind = kind if kind in KINDS else "fact"
        now = ts or time.time()
        with self._lock:
            if dedup:
                for row in self._bm25_rows("facts", text, project=None, limit=10):
                    if row["superseded_by"] is None and jaccard(row["text"], text) >= 0.85:
                        self.touch(row["id"])
                        return row["id"], "NOOP"
            vec = None
            if embed:
                arr = self.embedder.documents([fact_doc(text, project, entities)])
                vec = None if arr is None else arr[0]
                if dedup and vec is not None:
                    for row, sim in self._dense_rows("facts", vec, limit=3):
                        if sim >= 0.97 and row["superseded_by"] is None:
                            self.touch(row["id"])
                            return row["id"], "NOOP"
            cur = self.conn.execute(
                "INSERT INTO facts(text, kind, project, entities, source, created, updated, last_seen, importance, embedding)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (text, kind, project or "global", entities or "", source or "", now, now, now,
                 int(importance or 2), to_blob(vec)),
            )
            fid = cur.lastrowid
            self._fts_put(fid, text, project or "global", entities or "")
            self.conn.commit()
            self._mat_cache.pop("facts", None)
            return fid, "ADD"

    def update_fact(self, fid, text, keep_original=False):
        text = re.sub(r"\s+", " ", text).strip()
        with self._lock:
            row = self.get_fact(fid)
            if not row:
                return False
            arr = self.embedder.documents([fact_doc(text, row["project"], row["entities"])])
            original = row["original"] or (row["text"] if keep_original else None)
            self.conn.execute(
                "UPDATE facts SET text=?, updated=?, last_seen=?, original=?, embedding=? WHERE id=?",
                (text, time.time(), time.time(), original, to_blob(None if arr is None else arr[0]), fid),
            )
            self._fts_put(fid, text, row["project"], row["entities"])
            self.conn.commit()
            self._mat_cache.pop("facts", None)
            return True

    def supersede(self, old_id, text, **kw):
        """Retire old fact, insert the replacement (Zep-style temporal invalidation)."""
        old = self.get_fact(old_id)
        if not old:
            return None
        kw.setdefault("kind", old["kind"])
        kw.setdefault("project", old["project"])
        kw.setdefault("entities", old["entities"])
        kw.setdefault("importance", old["importance"])
        new_id, _ = self.add_fact(text, dedup=False, **kw)
        with self._lock:
            self.conn.execute("UPDATE facts SET superseded_by=?, updated=? WHERE id=?", (new_id, time.time(), old_id))
            self.conn.execute("DELETE FROM facts_fts WHERE rowid=?", (old_id,))
            self.conn.commit()
            self._mat_cache.pop("facts", None)
        return new_id

    def forget(self, fid):
        """Retire without replacement (superseded_by = -1)."""
        with self._lock:
            self.conn.execute("UPDATE facts SET superseded_by=-1, updated=? WHERE id=?", (time.time(), fid))
            self.conn.execute("DELETE FROM facts_fts WHERE rowid=?", (fid,))
            self.conn.commit()
            self._mat_cache.pop("facts", None)

    def touch(self, fid):
        self.conn.execute("UPDATE facts SET hits = hits + 1, last_seen = ? WHERE id = ?", (time.time(), fid))
        self.conn.commit()

    def get_fact(self, fid):
        return self.conn.execute("SELECT * FROM facts WHERE id = ?", (fid,)).fetchone()

    def live_facts(self, project=None):
        sql = "SELECT * FROM facts WHERE superseded_by IS NULL"
        args = []
        if project:
            sql += " AND project = ?"
            args.append(project)
        return self.conn.execute(sql + " ORDER BY id", args).fetchall()

    def embed_missing(self, table="facts", batch=256):
        """Backfill embeddings. Returns count embedded (0 if embedder down)."""
        n = 0
        while True:
            cols = "id, text, project, entities" if table == "facts" else "id, text"
            rows = self.conn.execute(
                f"SELECT {cols} FROM {table} WHERE embedding IS NULL LIMIT ?", (batch,)
            ).fetchall()
            if not rows:
                break
            docs = [fact_doc(r["text"], r["project"], r["entities"]) if table == "facts" else r["text"]
                    for r in rows]
            arr = self.embedder.documents(docs)
            if arr is None:
                break
            with self._lock:
                self.conn.executemany(
                    f"UPDATE {table} SET embedding=? WHERE id=?",
                    [(to_blob(v), r["id"]) for v, r in zip(arr, rows)],
                )
                self.conn.commit()
            n += len(rows)
        self._mat_cache.pop(table, None)
        return n

    # ------------------------------------------------------------------ retrieval primitives

    def _bm25_rows(self, table, query, project=None, limit=POOL, extra="", args=()):
        match = self._match(query)
        if not match:
            return []
        fts = f"{table}_fts"
        sql = (f"SELECT t.*, bm25({fts}) AS bm FROM {fts} JOIN {table} t ON t.id = {fts}.rowid "
               f"WHERE {fts} MATCH ? {extra}")
        params = [match, *args]
        if project and table != "docs":
            sql += " AND t.project = ?"
            params.append(project)
        sql += " ORDER BY bm LIMIT ?"
        params.append(limit)
        try:
            return self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS query failed (%s): %s", match, e)
            return []

    def _matrix(self, table):
        cached = self._mat_cache.get(table)
        count = self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE embedding IS NOT NULL").fetchone()[0]
        if cached and cached[0] == count:
            return cached[1], cached[2]
        rows = self.conn.execute(f"SELECT id, embedding FROM {table} WHERE embedding IS NOT NULL").fetchall()
        if not rows:
            return [], None
        ids = [r["id"] for r in rows]
        mat = np.vstack([from_blob(r["embedding"]) for r in rows])
        self._mat_cache[table] = (count, ids, mat)
        return ids, mat

    def _dense_rows(self, table, qvec, limit=POOL):
        ids, mat = self._matrix(table)
        if mat is None or qvec is None or mat.shape[1] != len(qvec):
            return []
        sims = mat @ qvec
        top = np.argsort(-sims)[: limit * 2]
        out = []
        for i in top:
            row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (ids[i],)).fetchone()
            if row is None:
                continue
            if table == "facts" and row["superseded_by"] is not None:
                continue
            out.append((row, float(sims[i])))
            if len(out) >= limit:
                break
        return out

    def _fuse(self, table, query, project=None, filters=None, qvec=None):
        """RRF over BM25 + dense. Returns {id: (row, rrf)}."""
        extra, args = filters or ("", ())
        fused = {}
        for rank, row in enumerate(self._bm25_rows(table, query, None, POOL, extra, args)):
            fused[row["id"]] = [row, 1.0 / (RRF_K + rank + 1)]
        if qvec is not None:
            dense = self._dense_rows(table, qvec, POOL)
            for rank, (row, sim) in enumerate(dense):
                if sim < 0.45:  # unrelated
                    continue
                if not self._passes(row, filters):
                    continue
                score = 1.0 / (RRF_K + rank + 1)
                if row["id"] in fused:
                    fused[row["id"]][1] += score
                else:
                    fused[row["id"]] = [row, score]
        return fused

    @staticmethod
    def _passes(row, filters):
        """Re-apply simple SQL filters to dense hits (kind / since / until)."""
        if not filters:
            return True
        _, args = filters
        meta = getattr(filters, "meta", None)
        return True if meta is None else meta(row)

    # ------------------------------------------------------------------ recall (facts)

    def recall(self, query, project=None, kind=None, since=None, limit=8, touch=True, raw=False):
        conds, args = ["AND t.superseded_by IS NULL"], []
        if kind:
            conds.append("AND t.kind = ?")
            args.append(kind)
        if since:
            conds.append("AND t.last_seen >= ?")
            args.append(since)
        filters = _Filters(" ".join(conds), tuple(args),
                           lambda r: (r["superseded_by"] is None and (not kind or r["kind"] == kind)
                                      and (not since or r["last_seen"] >= since)))
        qvec = self.embedder.query(query)
        fused = self._fuse("facts", query, project, filters, qvec)
        now = time.time()
        scored = []
        for fid, (row, rrf) in fused.items():
            age = (now - max(row["updated"], row["last_seen"])) / DAY
            recency = 0.75 + 0.25 * math.exp(-age / 60)
            importance = {1: 0.9, 2: 1.0, 3: 1.15}.get(row["importance"], 1.0)
            proj = 1.25 if project and row["project"] == project else (1.0 if row["project"] == "global" else 0.9)
            scored.append((rrf * recency * importance * (proj if project else 1.0), row))
        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]
        if raw:
            return [r for _, r in top]
        if touch:
            with self._lock:
                for _, r in top:
                    self.conn.execute("UPDATE facts SET hits=hits+1, last_seen=? WHERE id=?", (now, r["id"]))
                self.conn.commit()
        return [
            {"id": r["id"], "kind": r["kind"], "project": r["project"], "text": r["text"],
             "date": time.strftime("%Y-%m-%d", time.localtime(r["updated"])), "score": round(s * 1000, 2)}
            for s, r in top
        ]

    # ------------------------------------------------------------------ episodes

    def ingest_summary(self, path, embed=True, force=False):
        """(Re)index one summary file. Returns number of chunks (0 if unchanged)."""
        path = Path(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return 0
        prev = self.conn.execute("SELECT mtime FROM episode_files WHERE file=?", (path.name,)).fetchone()
        if prev and prev[0] >= mtime and not force:
            return 0
        try:
            meta, chunks = parse_summary(path)
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Skip summary %s: %s", path.name, e)
            return 0
        vecs = self.embedder.documents([c[1] for c in chunks]) if embed and chunks else None
        with self._lock:
            old = [r[0] for r in self.conn.execute("SELECT id FROM episodes WHERE file=?", (path.name,))]
            for oid in old:
                self.conn.execute("DELETE FROM episodes_fts WHERE rowid=?", (oid,))
            self.conn.execute("DELETE FROM episodes WHERE file=?", (path.name,))
            for i, (section, text) in enumerate(chunks):
                cur = self.conn.execute(
                    "INSERT INTO episodes(file, session, project, cwd, title, day, ts, section, text, embedding)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (meta["file"], meta["session"], meta["project"], meta["cwd"], meta["title"], meta["day"],
                     meta["ts"], section, text, to_blob(None if vecs is None else vecs[i])),
                )
                self.conn.execute(
                    "INSERT INTO episodes_fts(rowid, text, project, section) VALUES (?,?,?,?)",
                    (cur.lastrowid, text, meta["project"], section),
                )
            self.conn.execute("INSERT OR REPLACE INTO episode_files VALUES (?, ?)", (path.name, mtime))
            self.conn.commit()
            self._mat_cache.pop("episodes", None)
        return len(chunks)

    def ingest_summaries(self, summary_dir, embed=False):
        n_files = n_chunks = 0
        for f in sorted(Path(summary_dir).glob("*.md")):
            c = self.ingest_summary(f, embed=embed)
            if c:
                n_files += 1
                n_chunks += c
        return n_files, n_chunks

    def timeline(self, project=None, since=None, until=None, query=None, limit=10):
        """Sessions in a time window, newest first. With `query`, ranked by relevance instead."""
        conds, args = [], []
        if project:
            conds.append("AND t.project = ?")
            args.append(project)
        if since:
            conds.append("AND t.day >= ?")
            args.append(since)
        if until:
            conds.append("AND t.day <= ?")
            args.append(until)
        if query:
            filt = _Filters(" ".join(conds), tuple(args),
                            lambda r: ((not project or r["project"] == project)
                                       and (not since or r["day"] >= since) and (not until or r["day"] <= until)))
            fused = self._fuse("episodes", query, None, filt, self.embedder.query(query))
            order, seen = [], set()
            for _, (row, s) in sorted(fused.items(), key=lambda kv: -kv[1][1]):
                if row["file"] not in seen:
                    seen.add(row["file"])
                    order.append((row["file"], row))
        else:
            where = "WHERE 1=1 " + " ".join(c.replace("t.", "") for c in conds)
            rows = self.conn.execute(
                f"SELECT file, MAX(ts) AS ts FROM episodes {where} GROUP BY file ORDER BY ts DESC LIMIT ?",
                (*args, limit),
            ).fetchall()
            order = [(r["file"], None) for r in rows]
        out = []
        for file, hit in order[:limit]:
            chunks = self.conn.execute(
                "SELECT * FROM episodes WHERE file=? ORDER BY id", (file,)
            ).fetchall()
            if not chunks:
                continue
            c0 = chunks[0]
            overview = next((c["text"] for c in chunks if c["section"] == "overview"), "")
            progress = [l for c in chunks if c["section"] == "progress" for l in c["text"].splitlines()]
            item = {
                "day": c0["day"], "project": c0["project"], "title": c0["title"], "file": file,
                "overview": overview[:600], "recent": [p[:220] for p in progress[-4:]],
            }
            if hit is not None and hit["section"] != "overview":
                item["match"] = hit["text"][:400]
            out.append(item)
        return out

    # ------------------------------------------------------------------ docs (hand-written pages)

    def index_docs(self, wiki_dir, subdirs=("skills",)):
        wiki_dir = Path(wiki_dir)
        with self._lock:
            self.conn.execute("DELETE FROM docs")
            self.conn.execute("DELETE FROM docs_fts")
            n = 0
            for sub in subdirs:
                for md in sorted((wiki_dir / sub).glob("*.md")):
                    rel = str(md.relative_to(wiki_dir))
                    text = md.read_text(errors="replace")
                    parts = re.split(r"^(?=## )", text, flags=re.M)
                    for part in parts:
                        part = part.strip()
                        if not part:
                            continue
                        head = part.splitlines()[0].lstrip("# ").strip()
                        for i in range(0, len(part), 1500):
                            chunk = part[i:i + 1500]
                            cur = self.conn.execute(
                                "INSERT INTO docs(path, section, text) VALUES (?,?,?)", (rel, head, chunk))
                            self.conn.execute(
                                "INSERT INTO docs_fts(rowid, path, section, text) VALUES (?,?,?,?)",
                                (cur.lastrowid, rel, head, chunk))
                            n += 1
            self.conn.commit()
            self._mat_cache.pop("docs", None)
        return n

    def search_docs(self, query, limit=3):
        fused = self._fuse("docs", query, None, None, self.embedder.query(query))
        top = sorted(fused.values(), key=lambda x: -x[1])[:limit]
        return [{"path": r["path"], "section": r["section"], "text": r["text"][:500]} for r, _ in top]

    # ------------------------------------------------------------------ stats

    def stats(self):
        q = lambda s: self.conn.execute(s).fetchone()[0]
        return {
            "facts_live": q("SELECT COUNT(*) FROM facts WHERE superseded_by IS NULL"),
            "facts_retired": q("SELECT COUNT(*) FROM facts WHERE superseded_by IS NOT NULL"),
            "facts_embedded": q("SELECT COUNT(*) FROM facts WHERE embedding IS NOT NULL"),
            "episodes": q("SELECT COUNT(*) FROM episodes"),
            "episode_files": q("SELECT COUNT(*) FROM episode_files"),
            "episodes_embedded": q("SELECT COUNT(*) FROM episodes WHERE embedding IS NOT NULL"),
            "docs": q("SELECT COUNT(*) FROM docs"),
            "aliases": q("SELECT COUNT(*) FROM aliases"),
        }


class _Filters(tuple):
    """(sql, args) for BM25 plus a python predicate for dense hits."""

    meta: dict

    def __new__(cls, sql, args, meta):
        obj = super().__new__(cls, (sql, args))
        obj.meta = meta
        return obj
