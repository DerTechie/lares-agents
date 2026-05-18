# SPDX-License-Identifier: MIT
"""Subprocess wrapper around `lares-akonadi-notify`.

The helper streams one NDJSON line per Akonadi `itemAdded` signal. This
wrapper parses each line, drops malformed ones with a warning, and yields
typed events. Async-context-manager managed so SIGTERM lands cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from types import TracebackType

    from lares.kmail.config import LaresConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class NotifyEvent:
    event: str
    item_id: int
    collection_id: int
    remote_id: str
    mimetype: str
    ts: str


def _default_helper_path() -> Path:
    return Path(str(resources.files("lares") / "_bin" / "lares-akonadi-notify"))


class Notify:
    def __init__(self, argv: Sequence[str]) -> None:
        self._argv = list(argv)
        self._proc: asyncio.subprocess.Process | None = None

    @classmethod
    def from_config(cls, config: LaresConfig) -> Self:
        helper = (
            Path(config.kmail.helper_binary_path)
            if config.kmail.helper_binary_path
            else _default_helper_path()
        )
        argv: list[str] = [
            str(helper),
            "--mimetype",
            "message/rfc822",
            "--collection-attr",
            "inbox",
        ]
        for name in config.kmail.watch.extra_collection_names:
            argv += ["--extra-collection", name]
        return cls(argv)

    @classmethod
    def from_command(cls, argv: Sequence[str]) -> Self:
        return cls(argv)

    async def __aenter__(self) -> Self:
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._proc is None or self._proc.returncode is not None:
            return
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except TimeoutError:
            self._proc.kill()
            await self._proc.wait()

    async def events(self) -> AsyncIterator[NotifyEvent]:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("Notify used outside async context manager")
        async for line in self._iter_lines(self._proc.stdout):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("notify: malformed NDJSON dropped: %s (%s)", line, exc)
                continue
            try:
                yield NotifyEvent(
                    event=str(payload["event"]),
                    item_id=int(payload["item_id"]),
                    collection_id=int(payload["collection_id"]),
                    remote_id=str(payload.get("remote_id", "")),
                    mimetype=str(payload.get("mimetype", "")),
                    ts=str(payload.get("ts", "")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("notify: event shape unexpected, dropped: %s (%s)", payload, exc)

    @staticmethod
    async def _iter_lines(stream: asyncio.StreamReader) -> AsyncIterator[str]:
        while True:
            raw = await stream.readline()
            if not raw:
                return
            yield raw.decode("utf-8", errors="replace").rstrip("\n")
