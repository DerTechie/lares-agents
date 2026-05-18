# SPDX-License-Identifier: MIT
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from lares.kmail.classifier import ClassifierError, FetchedItem, Verdict
from lares.kmail.mutate import FetchResult, MutateError
from lares.kmail.notify import NotifyEvent
from lares.kmail.service import consume_one_event, drain_one_due
from lares.kmail.state import ItemState, QueueRow, State
from lares.kmail.tags import LARES_ERROR, LARES_PENDING, LARES_UNCLASSIFIED


@dataclass
class StubMutate:
    fetched: dict[int, FetchResult] = field(default_factory=dict[int, FetchResult])
    set_tags_calls: list[tuple[int, list[str]]] = field(default_factory=list[tuple[int, list[str]]])
    fetch_errors: dict[int, MutateError] = field(default_factory=dict[int, MutateError])

    async def fetch(self, item_id: int) -> FetchResult:
        if item_id in self.fetch_errors:
            raise self.fetch_errors[item_id]
        return self.fetched[item_id]

    async def set_tags(self, item_id: int, tags: list[str]) -> list[str]:
        self.set_tags_calls.append((item_id, list(tags)))
        return tags


@dataclass
class StubClassifier:
    verdicts: dict[int, Verdict] = field(default_factory=dict[int, Verdict])
    errors: dict[int, ClassifierError] = field(default_factory=dict[int, ClassifierError])

    async def classify(self, item: FetchedItem) -> Verdict:
        if item.item_id in self.errors:
            raise self.errors[item.item_id]
        return self.verdicts[item.item_id]


def _fetch(item_id: int, tags: list[str] | None = None) -> FetchResult:
    return FetchResult(
        item_id=item_id,
        headers={"From": "a@x", "To": "b@x", "Subject": "s", "List-Id": "", "Date": ""},
        body_text="b",
        tags=tags or [],
    )


def _ev(item_id: int) -> NotifyEvent:
    return NotifyEvent(
        event="item_added",
        item_id=item_id,
        collection_id=1,
        remote_id="<x>",
        mimetype="message/rfc822",
        ts="2026-05-18T12:00:00Z",
    )


@pytest.mark.asyncio
async def test_skip_when_item_already_has_lares_tag() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={5: _fetch(5, ["lares-personal"])})
    classifier = StubClassifier()
    await consume_one_event(_ev(5), mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls == []
    assert state.get(5) is None  # we don't write sqlite for already-tagged items


@pytest.mark.asyncio
async def test_classify_happy_path_records_verdict_and_no_retry() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={9: _fetch(9, [])})
    classifier = StubClassifier(
        verdicts={9: Verdict(tag="lares-personal", raw_category="personal", confidence=0.95)}
    )
    await consume_one_event(_ev(9), mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls == [(9, [LARES_PENDING]), (9, ["lares-personal"])]
    row = state.get(9)
    assert row is not None
    assert row.state is ItemState.CLASSIFIED
    assert row.verdict == "lares-personal"
    assert state.queue_depth() == 0


@pytest.mark.asyncio
async def test_low_confidence_applies_unclassified_tag() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={9: _fetch(9, [])})
    classifier = StubClassifier(
        verdicts={9: Verdict(tag=LARES_UNCLASSIFIED, raw_category="newsletter", confidence=0.31)}
    )
    await consume_one_event(_ev(9), mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls[-1] == (9, [LARES_UNCLASSIFIED])


@pytest.mark.asyncio
async def test_classifier_error_leaves_pending_and_enqueues() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={9: _fetch(9, [])})
    classifier = StubClassifier(errors={9: ClassifierError("ollama down")})
    await consume_one_event(_ev(9), mutate, classifier, state, max_retries=10)
    # pending tag stays
    assert mutate.set_tags_calls == [(9, [LARES_PENDING])]
    row = state.get(9)
    assert row is not None
    assert row.state is ItemState.PENDING
    assert state.queue_depth() == 1


@pytest.mark.asyncio
async def test_retries_exceeded_records_error_and_flips_tag() -> None:
    state = State(":memory:")
    # Pre-seed: item already at 10 attempts (= max_retries cap).
    state.record_pending(9)
    for _ in range(10):
        state.bump_attempts(9, "x")
    mutate = StubMutate(fetched={9: _fetch(9, [LARES_PENDING])})
    classifier = StubClassifier(errors={9: ClassifierError("still down")})
    qr = QueueRow(item_id=9, due_at=datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC), reason="x")
    await drain_one_due(qr, mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls[-1] == (9, [LARES_ERROR])
    row = state.get(9)
    assert row is not None
    assert row.state is ItemState.ERROR
    assert state.queue_depth() == 0


@pytest.mark.asyncio
async def test_drain_skips_deleted_item() -> None:
    state = State(":memory:")
    state.record_pending(9)
    mutate = StubMutate(
        fetch_errors={9: MutateError("gone", "not_found")},
    )
    classifier = StubClassifier()
    qr = QueueRow(item_id=9, due_at=datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC), reason="x")
    await drain_one_due(qr, mutate, classifier, state, max_retries=10)
    row = state.get(9)
    assert row is not None
    assert row.state is ItemState.ERROR
    assert row.last_error == "item_deleted"
    assert state.queue_depth() == 0
