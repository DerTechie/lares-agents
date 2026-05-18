# SPDX-License-Identifier: MIT
"""Asyncio service for the kmail triage agent.

Owns the single event loop, supervises the two subprocess helpers and the
HTTP classifier, and runs two concurrent tasks: `consume_new_mail`
(triggered by Akonadi `item_added` events) and `drain_retry_queue`
(timer/event-driven retries).

The per-message handlers are split into pure async functions
(`consume_one_event`, `drain_one_due`) that take their collaborators
explicitly — this is the surface the unit tests exercise.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import TYPE_CHECKING, Protocol

from lares.kmail.classifier import Classifier, ClassifierError, FetchedItem, Verdict
from lares.kmail.mutate import FetchResult, Mutate, MutateError
from lares.kmail.notify import Notify, NotifyEvent
from lares.kmail.state import QueueRow, State
from lares.kmail.tags import LARES_ERROR, LARES_PENDING, is_lares_tag

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from lares.kmail.config import LaresConfig

logger = logging.getLogger(__name__)


class _MutateLike(Protocol):
    async def fetch(self, item_id: int) -> FetchResult: ...
    async def set_tags(self, item_id: int, tags: list[str]) -> list[str]: ...


class _ClassifierLike(Protocol):
    async def classify(self, item: FetchedItem) -> Verdict: ...


def _to_fetched(fr: FetchResult) -> FetchedItem:
    return FetchedItem(item_id=fr.item_id, headers=fr.headers, body_text=fr.body_text)


async def _classify_and_apply(
    fr: FetchResult,
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
) -> None:
    """Classify `fr` and record the outcome. Called after LARES_PENDING is set."""
    item_id = fr.item_id
    try:
        verdict = await classifier.classify(_to_fetched(fr))
    except ClassifierError as exc:
        attempts = state.bump_attempts(item_id, str(exc))
        if attempts > max_retries:
            await mutate.set_tags(item_id, [LARES_ERROR])
            state.record_error(item_id, "exhausted_retries")
            return
        state.enqueue_retry(item_id, reason=str(exc))
        return

    await mutate.set_tags(item_id, [verdict.tag])
    state.record_classified(item_id, verdict.tag)


async def consume_one_event(
    event: NotifyEvent,
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
) -> None:
    """Handle a single Akonadi item_added event end-to-end."""
    try:
        fr = await mutate.fetch(event.item_id)
    except MutateError as exc:
        logger.warning("fetch failed for item_id=%d code=%s: %s", event.item_id, exc.code, exc)
        return
    if any(is_lares_tag(t) for t in fr.tags):
        logger.debug("skipping item_id=%d (already has lares-* tag)", event.item_id)
        return
    await mutate.set_tags(event.item_id, [LARES_PENDING])
    state.record_pending(event.item_id)
    await _classify_and_apply(fr, mutate, classifier, state, max_retries=max_retries)


async def drain_one_due(
    queue_row: QueueRow,
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
) -> None:
    """Process one due retry-queue entry."""
    try:
        fr = await mutate.fetch(queue_row.item_id)
    except MutateError as exc:
        if exc.code == "not_found":
            state.record_error(queue_row.item_id, "item_deleted")
            return
        # Transient mutate failure — bump and reschedule.
        attempts = state.bump_attempts(queue_row.item_id, str(exc))
        if attempts > max_retries:
            try:
                await mutate.set_tags(queue_row.item_id, [LARES_ERROR])
            except MutateError:
                logger.warning("could not flip tag to error for item_id=%d", queue_row.item_id)
            state.record_error(queue_row.item_id, "exhausted_retries")
            return
        state.enqueue_retry(queue_row.item_id, reason=str(exc))
        return
    await _classify_and_apply(fr, mutate, classifier, state, max_retries=max_retries)


async def _consume_loop(
    notify: Notify,
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
) -> None:
    async for event in notify.events():
        await consume_one_event(event, mutate, classifier, state, max_retries=max_retries)


async def _drain_loop(
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
    tick_s: float = 5.0,
) -> None:
    while True:
        due = state.pop_due(limit=10)
        for qr in due:
            await drain_one_due(qr, mutate, classifier, state, max_retries=max_retries)
        await asyncio.sleep(tick_s)


async def run(config: LaresConfig) -> None:
    state = State(config.kmail.state_db_path)
    try:
        async with (
            Notify.from_config(config) as notify,
            Mutate.from_config(config) as mutate,
            Classifier(config) as classifier,
            asyncio.TaskGroup() as tg,
        ):
            tg.create_task(
                _consume_loop(
                    notify,
                    mutate,
                    classifier,
                    state,
                    max_retries=config.kmail.max_retries,
                )
            )
            tg.create_task(
                _drain_loop(
                    mutate,
                    classifier,
                    state,
                    max_retries=config.kmail.max_retries,
                )
            )
    finally:
        state.close()


def _install_signal_shutdown(  # pyright: ignore[reportUnusedFunction] — wired by the CLI entry point in a later task
    loop: asyncio.AbstractEventLoop,
) -> Callable[[], Awaitable[None]]:
    stop_event = asyncio.Event()

    def _handler() -> None:
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handler)

    async def wait_stop() -> None:
        await stop_event.wait()

    return wait_stop
