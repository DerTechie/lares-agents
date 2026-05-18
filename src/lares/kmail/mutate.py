# SPDX-License-Identifier: MIT
"""Subprocess wrapper around `lares-akonadi-mutate`.

Long-running helper process; one request line in, one response line out.
Concurrent callers are serialized through an internal `asyncio.Lock` so
the stdio framing stays in step.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

    from lares.kmail.config import LaresConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class FetchResult:
    item_id: int
    headers: dict[str, str]
    body_text: str
    tags: list[str]


class MutateError(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def _default_helper_path() -> Path:
    return Path(str(resources.files("lares") / "_bin" / "lares-akonadi-mutate"))


class Mutate:
    def __init__(self, argv: Sequence[str]) -> None:
        self._argv = list(argv)
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)

    @classmethod
    def from_config(cls, config: LaresConfig) -> Self:
        helper = (
            Path(config.kmail.helper_binary_path)
            if config.kmail.helper_binary_path
            else _default_helper_path()
        )
        return cls(
            [
                str(helper),
                "--max-body-bytes",
                str(config.kmail.body_truncate_bytes),
            ]
        )

    @classmethod
    def from_command(cls, argv: Sequence[str]) -> Self:
        return cls(argv)

    async def __aenter__(self) -> Self:
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
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

    async def fetch(self, item_id: int) -> FetchResult:
        resp = await self._call({"op": "fetch", "item_id": item_id})
        try:
            return FetchResult(
                item_id=int(resp["item_id"]),
                headers={str(k): str(v) for k, v in dict(resp["headers"]).items()},
                body_text=str(resp.get("body_text", "")),
                tags=[str(t) for t in resp.get("tags", [])],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MutateError(f"malformed fetch response: {resp}", "internal") from exc

    async def set_tags(self, item_id: int, tags: list[str]) -> list[str]:
        resp = await self._call({"op": "set_tags", "item_id": item_id, "tags": tags})
        return [str(t) for t in resp.get("tags", [])]

    async def _call(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Mutate used outside async context manager")
        req_id = f"req-{next(self._ids)}"
        envelope: dict[str, Any] = {"id": req_id, **body}
        line = (json.dumps(envelope) + "\n").encode()

        async with self._lock:
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()
            raw = await self._proc.stdout.readline()

        if not raw:
            raise MutateError("mutate helper closed stdout", "internal")
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MutateError(f"non-JSON mutate response: {raw!r}", "internal") from exc

        if resp.get("id") != req_id:
            raise MutateError(
                f"request id mismatch: sent={req_id} got={resp.get('id')}", "internal"
            )
        if not resp.get("ok"):
            raise MutateError(
                str(resp.get("error", "mutate failed")),
                str(resp.get("code", "internal")),
            )
        return resp
