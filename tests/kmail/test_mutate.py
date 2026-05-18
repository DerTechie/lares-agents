# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from lares.kmail.mutate import Mutate, MutateError


def _echo_stub(tmp_path: Path) -> Path:
    script = tmp_path / "stub_mutate.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, sys
            for line in sys.stdin:
                req = json.loads(line)
                if req["op"] == "fetch":
                    resp = {
                        "id": req["id"], "ok": True, "item_id": req["item_id"],
                        "headers": {"From": "a@x", "To": "b@x", "Subject": "S",
                                    "List-Id": "", "Date": ""},
                        "body_text": "hello", "tags": ["lares-pending"],
                    }
                elif req["op"] == "set_tags":
                    resp = {
                        "id": req["id"], "ok": True, "item_id": req["item_id"],
                        "tags": req["tags"],
                    }
                else:
                    resp = {"id": req["id"], "ok": False,
                            "error": "bad op", "code": "bad_request"}
                print(json.dumps(resp), flush=True)
            """
        )
    )
    return script


def _error_stub(tmp_path: Path, code: str = "akonadi_offline") -> Path:
    script = tmp_path / "stub_mutate_err.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            for line in sys.stdin:
                req = json.loads(line)
                resp = {{"id": req["id"], "ok": False,
                         "error": "akonadi down", "code": "{code}"}}
                print(json.dumps(resp), flush=True)
            """
        )
    )
    return script


@pytest.mark.asyncio
async def test_fetch_round_trips(tmp_path: Path) -> None:
    async with Mutate.from_command([sys.executable, str(_echo_stub(tmp_path))]) as m:
        result = await m.fetch(42)
    assert result.item_id == 42
    assert result.body_text == "hello"
    assert result.tags == ["lares-pending"]
    assert result.headers["From"] == "a@x"


@pytest.mark.asyncio
async def test_set_tags_round_trips(tmp_path: Path) -> None:
    async with Mutate.from_command([sys.executable, str(_echo_stub(tmp_path))]) as m:
        result = await m.set_tags(42, ["lares-personal"])
    assert result == ["lares-personal"]


@pytest.mark.asyncio
async def test_error_response_raises_mutate_error(tmp_path: Path) -> None:
    async with Mutate.from_command([sys.executable, str(_error_stub(tmp_path))]) as m:
        with pytest.raises(MutateError) as ei:
            await m.fetch(1)
    assert ei.value.code == "akonadi_offline"


@pytest.mark.asyncio
async def test_not_found_error_exposes_code(tmp_path: Path) -> None:
    async with Mutate.from_command(
        [sys.executable, str(_error_stub(tmp_path, code="not_found"))]
    ) as m:
        with pytest.raises(MutateError) as ei:
            await m.fetch(404)
    assert ei.value.code == "not_found"


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized(tmp_path: Path) -> None:
    async with Mutate.from_command([sys.executable, str(_echo_stub(tmp_path))]) as m:
        results = await asyncio.gather(m.fetch(1), m.fetch(2), m.fetch(3))
    assert [r.item_id for r in results] == [1, 2, 3]
