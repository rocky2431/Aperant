"""
Ultra Builder Pro — SQLite FTS5 Memory
========================================

Lightweight full-text search memory layer using SQLite FTS5.
Zero external dependencies — uses Python's built-in sqlite3 module.

This provides fast, persistent pattern/finding storage for Ultra Builder
workflows, serving as the middle tier between file-based memory (simple)
and Graphiti (semantic graph).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single memory entry."""
    id: int
    entry_type: str  # pattern, finding, gotcha, insight
    content: str
    metadata: dict[str, Any]
    confidence: str  # fact, inference, speculation
    occurrences: int
    created_at: str
    updated_at: str


class FTSMemory:
    """SQLite FTS5 based memory store.

    Database is created at ``{base_dir}/memory/memory.db``.

    Supports context manager protocol::

        with FTSMemory(spec_dir) as memory:
            memory.save_pattern("Always use parameterized SQL", confidence="fact")
            results = memory.search("SQL injection")
    """

    def __enter__(self) -> FTSMemory:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __init__(self, base_dir: Path) -> None:
        self._db_dir = base_dir / "memory"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._db_dir / "memory.db"
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                confidence TEXT DEFAULT 'speculation',
                occurrences INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                entry_type,
                content='memories',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories
            BEGIN
                INSERT INTO memories_fts(rowid, content, entry_type)
                VALUES (new.id, new.content, new.entry_type);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories
            BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, entry_type)
                VALUES ('delete', old.id, old.content, old.entry_type);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories
            BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, entry_type)
                VALUES ('delete', old.id, old.content, old.entry_type);
                INSERT INTO memories_fts(rowid, content, entry_type)
                VALUES (new.id, new.content, new.entry_type);
            END;
        """)
        conn.commit()

    def save_pattern(
        self,
        content: str,
        confidence: str = "speculation",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save a learned pattern."""
        return self._save("pattern", content, confidence, metadata)

    def save_finding(
        self,
        content: str,
        confidence: str = "fact",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save a review finding."""
        return self._save("finding", content, confidence, metadata)

    def save_gotcha(
        self,
        content: str,
        confidence: str = "inference",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save a gotcha/pitfall."""
        return self._save("gotcha", content, confidence, metadata)

    def _save(
        self,
        entry_type: str,
        content: str,
        confidence: str,
        metadata: dict[str, Any] | None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO memories (entry_type, content, metadata, confidence, occurrences, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (entry_type, content, json.dumps(metadata or {}), confidence, now, now),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Full-text search across all memory entries."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT m.* FROM memories m
                   JOIN memories_fts f ON m.id = f.rowid
                   WHERE memories_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS query syntax error — fall back to LIKE
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE content LIKE ?
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (f"%{query}%", limit),
            ).fetchall()

        return [self._row_to_entry(row) for row in rows]

    def increment_occurrences(self, entry_id: int) -> None:
        """Bump the occurrence count for a pattern (for confidence escalation)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE memories SET occurrences = occurrences + 1, updated_at = ? WHERE id = ?",
            (now, entry_id),
        )
        conn.commit()

    def update_confidence(self, entry_id: int, confidence: str) -> None:
        """Update the confidence level of an entry."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE memories SET confidence = ?, updated_at = ? WHERE id = ?",
            (confidence, now, entry_id),
        )
        conn.commit()

    def get_patterns(self, confidence: str | None = None) -> list[MemoryEntry]:
        """Get all patterns, optionally filtered by confidence."""
        conn = self._get_conn()
        if confidence:
            rows = conn.execute(
                "SELECT * FROM memories WHERE entry_type = 'pattern' AND confidence = ? ORDER BY occurrences DESC",
                (confidence,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE entry_type = 'pattern' ORDER BY occurrences DESC"
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        try:
            metadata = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt metadata for memory entry %d", row["id"])
            metadata = {}
        return MemoryEntry(
            id=row["id"],
            entry_type=row["entry_type"],
            content=row["content"],
            metadata=metadata,
            confidence=row["confidence"],
            occurrences=row["occurrences"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
