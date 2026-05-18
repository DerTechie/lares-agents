# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from lares.kmail.notify import Notify, NotifyEvent


def _stub_script(tmp_path: Path, lines: list[str]) -> Path:
    body = ", ".join(repr(line) for line in lines)
    script = tmp_path / "stub_notify.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import time
            lines = [{body}]
            for line in lines:
                print(line, flush=True)
            # stay alive so the test can stop us
            time.sleep(60)
            """
        )
    )
    return script


@pytest.mark.asyncio
async def test_notify_yields_parsed_events(tmp_path: Path) -> None:
    script = _stub_script(
        tmp_path,
        [
            '{"event":"item_added","item_id":1,"collection_id":10,"remote_id":"<a@x>","mimetype":"message/rfc822","ts":"2026-05-18T12:00:00Z"}',
            '{"event":"item_added","item_id":2,"collection_id":10,"remote_id":"<b@x>","mimetype":"message/rfc822","ts":"2026-05-18T12:00:01Z"}',
        ],
    )

    async with Notify.from_command([sys.executable, str(script)]) as notify:
        collected: list[NotifyEvent] = []

        async def collect() -> None:
            async for ev in notify.events():
                collected.append(ev)
                if len(collected) == 2:
                    return

        await asyncio.wait_for(collect(), timeout=5)

    assert [e.item_id for e in collected] == [1, 2]
    assert collected[0].mimetype == "message/rfc822"


@pytest.mark.asyncio
async def test_notify_skips_malformed_lines(tmp_path: Path) -> None:
    script = _stub_script(
        tmp_path,
        [
            "not json at all",
            '{"event":"item_added","item_id":7,"collection_id":1,"remote_id":"<x>","mimetype":"message/rfc822","ts":"2026-05-18T12:00:00Z"}',
        ],
    )
    async with Notify.from_command([sys.executable, str(script)]) as notify:

        async def first_event() -> NotifyEvent:
            async for ev in notify.events():
                return ev
            raise AssertionError("no events")

        ev = await asyncio.wait_for(first_event(), timeout=5)
    assert ev.item_id == 7


@pytest.mark.asyncio
async def test_notify_exit_stops_iteration(tmp_path: Path) -> None:
    script = tmp_path / "exits_quick.py"
    script.write_text("import sys; sys.exit(0)")
    async with Notify.from_command([sys.executable, str(script)]) as notify:
        events: list[NotifyEvent] = []
        async for ev in notify.events():
            events.append(ev)
    assert events == []
