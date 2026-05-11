"""SQLite-backed fact store with entity resolution and trust scoring."""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

import holographic as hrr

_DEFAULT_DB = Path.home() / ".claude" / "holographic-memory" / "memory.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT NOT NULL UNIQUE,
    category        TEXT DEFAULT 'general',
    tags            TEXT DEFAULT '',
    trust_score     REAL DEFAULT 0.5,
    retrieval_count INTEGER DEFAULT 0,
    helpful_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hrr_vector      BLOB,
    project_path    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    entity_type TEXT DEFAULT 'unknown',
    aliases     TEXT DEFAULT '',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_entities (
    fact_id   INTEGER REFERENCES facts(fact_id),
    entity_id INTEGER REFERENCES entities(entity_id),
    PRIMARY KEY (fact_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_facts_trust    ON facts(trust_score DESC);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_entities_name  ON entities(name);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(content, tags, content=facts, content_rowid=fact_id);

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, tags)
        VALUES (new.fact_id, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
        VALUES ('delete', old.fact_id, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
        VALUES ('delete', old.fact_id, old.content, old.tags);
    INSERT INTO facts_fts(rowid, content, tags)
        VALUES (new.fact_id, new.content, new.tags);
END;
"""

_SIMILARITY_DEDUP_THRESHOLD = 0.85
_DEDUP_CANDIDATE_LIMIT = 20
_DEDUP_FALLBACK_LIMIT = 200

_RE_FTS_WORD = re.compile(r"\w+")

_HELPFUL_DELTA   =  0.05
_UNHELPFUL_DELTA = -0.10
_TRUST_MIN       =  0.0
_TRUST_MAX       =  1.0

_RE_CAPITALIZED  = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
_RE_DOUBLE_QUOTE = re.compile(r'"([^"]+)"')
_RE_SINGLE_QUOTE = re.compile(r"'([^']+)'")
_RE_AKA          = re.compile(
    r'(\w+(?:\s+\w+)*)\s+(?:aka|also known as)\s+(\w+(?:\s+\w+)*)',
    re.IGNORECASE,
)


def _clamp_trust(value: float) -> float:
    return max(_TRUST_MIN, min(_TRUST_MAX, value))


def _fts_or_query(text: str) -> str:
    """Build a safe FTS5 OR query from text words. Returns '' if nothing usable."""
    words = {w.lower() for w in _RE_FTS_WORD.findall(text) if len(w) >= 3}
    if not words:
        return ""
    return " OR ".join(sorted(words)[:32])


class MemoryStore:
    def __init__(
        self,
        db_path: "str | Path | None" = None,
        default_trust: float = 0.5,
        hrr_dim: int = 1024,
    ) -> None:
        if db_path is None:
            db_path = _DEFAULT_DB
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_trust = _clamp_trust(default_trust)
        self.hrr_dim = hrr_dim
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA mmap_size=67108864",
            "PRAGMA cache_size=-20000",
        ):
            try:
                self._conn.execute(pragma)
            except Exception:
                pass
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self._conn.executescript(_SCHEMA)
            self._conn.execute("PRAGMA user_version = 1")
            self._conn.commit()

    def add_fact(
        self,
        content: str,
        category: str = "general",
        tags: str = "",
        project_path: str = "",
    ) -> int:
        with self._lock:
            content = content.strip()
            if not content:
                raise ValueError("content must not be empty")

            existing_id = self._find_similar(content, category)
            if existing_id is not None:
                self._conn.execute(
                    """
                    UPDATE facts
                    SET trust_score = MIN(?, trust_score + ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE fact_id = ?
                    """,
                    (_TRUST_MAX, _HELPFUL_DELTA, existing_id),
                )
                self._conn.commit()
                return existing_id

            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO facts (content, category, tags, trust_score, project_path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (content, category, tags, self.default_trust, project_path),
                )
                self._conn.commit()
                fact_id: int = cur.lastrowid  # type: ignore[assignment]
            except sqlite3.IntegrityError:
                row = self._conn.execute(
                    "SELECT fact_id FROM facts WHERE content = ?", (content,)
                ).fetchone()
                return int(row["fact_id"])

            for name in self._extract_entities(content):
                entity_id = self._resolve_entity(name)
                self._link_fact_entity(fact_id, entity_id)
            self._conn.commit()

            self._compute_hrr_vector(fact_id, content)
            return fact_id

    def _find_similar(self, content: str, category: str) -> int | None:
        """HRR near-duplicate detector. Returns existing fact_id if sim > threshold.

        FTS5 narrows candidates from full-category scan to top-N BM25 matches
        before the O(N·dim) HRR comparison.
        """
        rows: list = []
        fts_query = _fts_or_query(content)
        if fts_query:
            try:
                rows = self._conn.execute(
                    """
                    SELECT f.fact_id, f.content
                    FROM facts_fts fts
                    JOIN facts f ON f.fact_id = fts.rowid
                    WHERE facts_fts MATCH ? AND f.category = ?
                    ORDER BY bm25(facts_fts) LIMIT ?
                    """,
                    (fts_query, category, _DEDUP_CANDIDATE_LIMIT),
                ).fetchall()
            except Exception:
                rows = []
        if not rows:
            rows = self._conn.execute(
                "SELECT fact_id, content FROM facts WHERE category = ? LIMIT ?",
                (category, _DEDUP_FALLBACK_LIMIT),
            ).fetchall()
        if not rows:
            return None
        query_vec = hrr.encode_text(content, self.hrr_dim)
        best_id, best_sim = None, _SIMILARITY_DEDUP_THRESHOLD
        for row in rows:
            fact_vec = hrr.encode_text(row["content"], self.hrr_dim)
            sim = hrr.similarity(query_vec, fact_vec)
            if sim > best_sim:
                best_sim = sim
                best_id = int(row["fact_id"])
        return best_id

    def search_facts(
        self,
        query: str,
        category: str | None = None,
        min_trust: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        with self._lock:
            query = query.strip()
            if not query:
                return []
            params: list = [query, min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND f.category = ?"
                params.append(category)
            params.append(limit)
            sql = f"""
                SELECT f.fact_id, f.content, f.category, f.tags,
                       f.trust_score, f.retrieval_count, f.helpful_count,
                       f.created_at, f.updated_at
                FROM facts f
                JOIN facts_fts fts ON fts.rowid = f.fact_id
                WHERE facts_fts MATCH ?
                  AND f.trust_score >= ?
                  {category_clause}
                ORDER BY fts.rank, f.trust_score DESC
                LIMIT ?
            """
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except Exception:
                return []
            results = [dict(r) for r in rows]
            if results:
                ids = [r["fact_id"] for r in results]
                placeholders = ",".join("?" * len(ids))
                self._conn.execute(
                    f"UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id IN ({placeholders})",
                    ids,
                )
                self._conn.commit()
            return results

    def update_fact(
        self,
        fact_id: int,
        content: str | None = None,
        trust_delta: float | None = None,
        tags: str | None = None,
        category: str | None = None,
    ) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return False
            assignments: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
            params: list = []
            if content is not None:
                assignments.append("content = ?")
                params.append(content.strip())
            if tags is not None:
                assignments.append("tags = ?")
                params.append(tags)
            if category is not None:
                assignments.append("category = ?")
                params.append(category)
            if trust_delta is not None:
                new_trust = _clamp_trust(row["trust_score"] + trust_delta)
                assignments.append("trust_score = ?")
                params.append(new_trust)
            params.append(fact_id)
            self._conn.execute(
                f"UPDATE facts SET {', '.join(assignments)} WHERE fact_id = ?", params,
            )
            self._conn.commit()
            if content is not None:
                self._conn.execute("DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,))
                for name in self._extract_entities(content):
                    entity_id = self._resolve_entity(name)
                    self._link_fact_entity(fact_id, entity_id)
                self._conn.commit()
                self._compute_hrr_vector(fact_id, content)
            return True

    def remove_fact(self, fact_id: int) -> bool:
        with self._lock:
            self._conn.execute("DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,))
            cur = self._conn.execute("DELETE FROM facts WHERE fact_id = ?", (fact_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def list_facts(
        self,
        category: str | None = None,
        min_trust: float = 0.0,
        limit: int = 50,
    ) -> list[dict]:
        with self._lock:
            params: list = [min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND category = ?"
                params.append(category)
            params.append(limit)
            sql = f"""
                SELECT fact_id, content, category, tags, trust_score,
                       retrieval_count, helpful_count, created_at, updated_at
                FROM facts
                WHERE trust_score >= ?
                  {category_clause}
                ORDER BY trust_score DESC
                LIMIT ?
            """
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def record_feedback(self, fact_id: int, helpful: bool) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score, helpful_count FROM facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"fact_id {fact_id} not found")
            old_trust: float = row["trust_score"]
            delta = _HELPFUL_DELTA if helpful else _UNHELPFUL_DELTA
            new_trust = _clamp_trust(old_trust + delta)
            helpful_increment = 1 if helpful else 0
            self._conn.execute(
                """
                UPDATE facts
                SET trust_score    = ?,
                    helpful_count  = helpful_count + ?,
                    updated_at     = CURRENT_TIMESTAMP
                WHERE fact_id = ?
                """,
                (new_trust, helpful_increment, fact_id),
            )
            self._conn.commit()
            return {
                "fact_id": fact_id,
                "old_trust": old_trust,
                "new_trust": new_trust,
                "helpful_count": row["helpful_count"] + helpful_increment,
            }

    def stats(self) -> tuple[int, list[tuple[str, int]]]:
        """Returns (total_count, [(category, count), ...]) for top 5 categories."""
        count = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        cats = self._conn.execute(
            "SELECT category, COUNT(*) as n FROM facts GROUP BY category ORDER BY n DESC LIMIT 5"
        ).fetchall()
        return count, [(row["category"], row["n"]) for row in cats]

    def project_count(self, project_path: str) -> int:
        """Count facts associated with a project path."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE project_path = ?", (project_path,)
        ).fetchone()
        return int(row[0]) if row else 0

    def _extract_entities(self, text: str) -> list[str]:
        seen: set[str] = set()
        candidates: list[str] = []

        def _add(name: str) -> None:
            stripped = name.strip()
            if stripped and stripped.lower() not in seen:
                seen.add(stripped.lower())
                candidates.append(stripped)

        for m in _RE_CAPITALIZED.finditer(text):
            _add(m.group(1))
        for m in _RE_DOUBLE_QUOTE.finditer(text):
            _add(m.group(1))
        for m in _RE_SINGLE_QUOTE.finditer(text):
            _add(m.group(1))
        for m in _RE_AKA.finditer(text):
            _add(m.group(1))
            _add(m.group(2))
        return candidates

    def _resolve_entity(self, name: str) -> int:
        row = self._conn.execute(
            "SELECT entity_id FROM entities WHERE name LIKE ?", (name,)
        ).fetchone()
        if row is not None:
            return int(row["entity_id"])
        alias_row = self._conn.execute(
            "SELECT entity_id FROM entities WHERE ',' || aliases || ',' LIKE '%,' || ? || ',%'",
            (name,),
        ).fetchone()
        if alias_row is not None:
            return int(alias_row["entity_id"])
        cur = self._conn.execute("INSERT INTO entities (name) VALUES (?)", (name,))
        return int(cur.lastrowid)  # type: ignore[return-value]

    def _link_fact_entity(self, fact_id: int, entity_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO fact_entities (fact_id, entity_id) VALUES (?, ?)",
            (fact_id, entity_id),
        )

    def _compute_hrr_vector(self, fact_id: int, content: str) -> None:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT e.name FROM entities e
                JOIN fact_entities fe ON fe.entity_id = e.entity_id
                WHERE fe.fact_id = ?
                """,
                (fact_id,),
            ).fetchall()
            entities = [row["name"] for row in rows]
            vector = hrr.encode_fact(content, entities, self.hrr_dim)
            self._conn.execute(
                "UPDATE facts SET hrr_vector = ? WHERE fact_id = ?",
                (hrr.phases_to_bytes(vector), fact_id),
            )
            self._conn.commit()

    def rebuild_all_vectors(self, dim: int | None = None) -> int:
        with self._lock:
            if dim is not None:
                self.hrr_dim = dim
            rows = self._conn.execute("SELECT fact_id, content FROM facts").fetchall()
            for row in rows:
                self._compute_hrr_vector(row["fact_id"], row["content"])
            return len(rows)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
