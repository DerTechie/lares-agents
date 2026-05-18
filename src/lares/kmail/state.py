# SPDX-License-Identifier: MIT
"""Sqlite-backed state for the kmail triage agent.

Two tables: `items` (one row per item we've touched) and `retry_queue`
(items awaiting reclassification with exponential backoff). All write
ops are synchronous; the service runs them in the default executor via
`asyncio.to_thread`.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


_BACKOFF_SCHEDULE = [
    timedelta(seconds=10),
    timedelta(seconds=30),
    timedelta(seconds=60),
    timedelta(seconds=300),
]


def backoff_delay(attempt: int) -> timedelta:
    """Return the delay before retry attempt N (0-indexed). Caps at 5 minutes."""
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt}")
    idx = min(attempt, len(_BACKOFF_SCHEDULE) - 1)
    return _BACKOFF_SCHEDULE[idx]


class ItemState(StrEnum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class ItemRow:
    item_id: int
    state: ItemState
    verdict: str | None
    last_attempt: datetime
    attempts: int
    last_error: str | None


@dataclass(slots=True, frozen=True)
class QueueRow:
    item_id: int
    due_at: datetime
    reason: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id      INTEGER PRIMARY KEY,
    state        TEXT NOT NULL,
    verdict      TEXT,
    last_attempt TIMESTAMP NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT
);
CREATE TABLE IF NOT EXISTS retry_queue (
    item_id   INTEGER PRIMARY KEY REFERENCES items(item_id),
    due_at    TIMESTAMP NOT NULL,
    reason    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retry_due ON retry_queue(due_at);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(raw: str | datetime) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    # sqlite returns TIMESTAMP columns as ISO 8601 strings.
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class State:
    def __init__(self, db_path: Path | str) -> None:
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(
            str(db_path),
            isolation_level=None,  # autocommit; we'll use BEGIN/COMMIT explicitly
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Connection, None, None]:
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def record_pending(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO items(item_id, state, last_attempt, attempts)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(item_id) DO UPDATE
                  SET state='pending', last_attempt=excluded.last_attempt
                """,
                (item_id, ItemState.PENDING.value, _now().isoformat()),
            )

    def record_classified(self, item_id: int, verdict: str) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO items(item_id, state, verdict, last_attempt, attempts)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(item_id) DO UPDATE
                  SET state='classified',
                      verdict=excluded.verdict,
                      last_attempt=excluded.last_attempt,
                      last_error=NULL
                """,
                (item_id, ItemState.CLASSIFIED.value, verdict, _now().isoformat()),
            )
            c.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))

    def record_error(self, item_id: int, reason: str) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO items(item_id, state, last_attempt, attempts, last_error)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(item_id) DO UPDATE
                  SET state='error',
                      last_attempt=excluded.last_attempt,
                      last_error=excluded.last_error
                """,
                (item_id, ItemState.ERROR.value, _now().isoformat(), reason),
            )
            c.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))

    def bump_attempts(self, item_id: int, reason: str) -> int:
        with self._tx() as c:
            cur = c.execute(
                """
                UPDATE items
                SET attempts = attempts + 1,
                    last_attempt = ?,
                    last_error = ?
                WHERE item_id = ?
                RETURNING attempts
                """,
                (_now().isoformat(), reason, item_id),
            )
            row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown item_id: {item_id}")
        return int(row["attempts"])

    def enqueue_retry(self, item_id: int, reason: str) -> None:
        row = self.get(item_id)
        attempt = 0 if row is None else row.attempts
        due_at = _now() + backoff_delay(attempt)
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO retry_queue(item_id, due_at, reason)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE
                  SET due_at=excluded.due_at, reason=excluded.reason
                """,
                (item_id, due_at.isoformat(), reason),
            )

    def remove_from_queue(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))

    def peek_next_due(self) -> QueueRow | None:
        cur = self._conn.execute(
            "SELECT item_id, due_at, reason FROM retry_queue ORDER BY due_at ASC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        return QueueRow(int(row["item_id"]), _parse_ts(row["due_at"]), str(row["reason"]))

    def pop_due(self, *, limit: int) -> list[QueueRow]:
        now_iso = _now().isoformat()
        cur = self._conn.execute(
            """
            SELECT item_id, due_at, reason FROM retry_queue
            WHERE due_at <= ? ORDER BY due_at ASC LIMIT ?
            """,
            (now_iso, limit),
        )
        return [
            QueueRow(int(r["item_id"]), _parse_ts(r["due_at"]), str(r["reason"]))
            for r in cur.fetchall()
        ]

    def get(self, item_id: int) -> ItemRow | None:
        cur = self._conn.execute(
            "SELECT item_id, state, verdict, last_attempt, attempts, last_error"
            " FROM items WHERE item_id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return ItemRow(
            item_id=int(row["item_id"]),
            state=ItemState(row["state"]),
            verdict=row["verdict"],
            last_attempt=_parse_ts(row["last_attempt"]),
            attempts=int(row["attempts"]),
            last_error=row["last_error"],
        )

    def max_item_id(self) -> int | None:
        cur = self._conn.execute("SELECT MAX(item_id) AS m FROM items")
        row = cur.fetchone()
        return int(row["m"]) if row and row["m"] is not None else None

    def queue_depth(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM retry_queue")
        row = cur.fetchone()
        return int(row["n"]) if row else 0
