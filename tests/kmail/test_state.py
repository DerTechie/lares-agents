# SPDX-License-Identifier: MIT
from datetime import UTC, datetime, timedelta
from pathlib import Path

from freezegun import freeze_time

from lares.kmail.state import ItemState, State, backoff_delay


def test_backoff_curve() -> None:
    assert backoff_delay(0) == timedelta(seconds=10)
    assert backoff_delay(1) == timedelta(seconds=30)
    assert backoff_delay(2) == timedelta(seconds=60)
    assert backoff_delay(3) == timedelta(seconds=300)
    assert backoff_delay(10) == timedelta(seconds=300)  # capped


def _open(tmp_path: Path) -> State:
    return State(tmp_path / "state.db")


def test_record_classified_creates_row() -> None:
    s = State(":memory:")
    s.record_classified(item_id=42, verdict="lares-personal")
    row = s.get(42)
    assert row is not None
    assert row.item_id == 42
    assert row.state is ItemState.CLASSIFIED
    assert row.verdict == "lares-personal"
    assert row.attempts == 0
    assert row.last_error is None


@freeze_time("2026-05-18 12:00:00")
def test_enqueue_retry_inserts_with_backoff() -> None:
    s = State(":memory:")
    s.record_pending(item_id=7)
    s.enqueue_retry(item_id=7, reason="ollama_down")
    due = s.peek_next_due()
    assert due is not None
    assert due.item_id == 7
    assert due.due_at == datetime(2026, 5, 18, 12, 0, 10, tzinfo=UTC)


@freeze_time("2026-05-18 12:00:00")
def test_enqueue_retry_uses_existing_attempts_count() -> None:
    s = State(":memory:")
    s.record_pending(item_id=7)
    s.enqueue_retry(item_id=7, reason="ollama_down")  # attempt 1 → 10s
    s.bump_attempts(7, "ollama_down")
    s.enqueue_retry(item_id=7, reason="ollama_down")  # attempt 2 → 30s
    due = s.peek_next_due()
    assert due is not None
    assert due.due_at == datetime(2026, 5, 18, 12, 0, 30, tzinfo=UTC)


@freeze_time("2026-05-18 12:00:00")
def test_pop_due_returns_only_due_items() -> None:
    s = State(":memory:")
    s.record_pending(item_id=1)
    s.record_pending(item_id=2)
    s.enqueue_retry(item_id=1, reason="x")  # due at +10s
    s.bump_attempts(2, "x")
    s.bump_attempts(2, "x")
    s.bump_attempts(2, "x")
    s.enqueue_retry(item_id=2, reason="x")  # attempt 4 → 300s

    with freeze_time("2026-05-18 12:00:15"):
        due_now = s.pop_due(limit=10)
    assert [d.item_id for d in due_now] == [1]


def test_max_item_id_returns_none_on_empty() -> None:
    s = State(":memory:")
    assert s.max_item_id() is None


def test_max_item_id_returns_max() -> None:
    s = State(":memory:")
    s.record_classified(item_id=5, verdict="lares-personal")
    s.record_classified(item_id=99, verdict="lares-business")
    s.record_pending(item_id=42)
    assert s.max_item_id() == 99


def test_remove_from_queue_idempotent() -> None:
    s = State(":memory:")
    s.record_pending(item_id=1)
    s.enqueue_retry(item_id=1, reason="x")
    s.remove_from_queue(1)
    s.remove_from_queue(1)  # double remove must not raise
    assert s.peek_next_due() is None


def test_record_error_after_cap(tmp_path: Path) -> None:
    s = _open(tmp_path)
    s.record_error(item_id=11, reason="exhausted_retries")
    row = s.get(11)
    assert row is not None
    assert row.state is ItemState.ERROR
    assert row.last_error == "exhausted_retries"
