# SPDX-License-Identifier: MIT
"""Regression test for the mutate helper's stdin reader (Bug B).

Drives the real `lares-akonadi-mutate` binary with three sequential `fetch`
ops over a single subprocess and asserts three responses come back. The
historical bug exited the helper after the first async op; the second op
raised `MutateError("mutate helper closed stdout", "internal")`.

Skips cleanly when:
- The helper binary is not materialised (editable installs via `uv sync`
  do not run CMake's install step; the canonical workaround is
  `uv tool install --reinstall .` plus pointing `LARES_HELPER_PATH` at
  the installed binary).
- Akonadi is not reachable. The bug only manifests when the helper's
  fetch path is genuinely async (ItemFetchJob queued on the event loop).
  Without a running Akonadi server, `handleFetch` early-returns
  synchronously via `ensureAkonadiOnline`, and the spurious-notifier
  fire we are guarding against does not occur. The test is therefore
  most useful on a developer machine with Akonadi running, and skips
  in container CI by design.
"""

from __future__ import annotations

import os
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from lares.kmail.mutate import Mutate, MutateError


def _helper_path() -> Path | None:
    env = os.environ.get("LARES_HELPER_PATH")
    if env:
        candidate = Path(env)
        return candidate if candidate.is_file() else None
    candidate = Path(str(resources.files("lares") / "_bin" / "lares-akonadi-mutate"))
    return candidate if candidate.is_file() else None


def _akonadi_up() -> bool:
    try:
        result = subprocess.run(
            ["qdbus6", "org.freedesktop.Akonadi"],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


@pytest.mark.asyncio
async def test_helper_handles_three_sequential_fetches() -> None:
    helper = _helper_path()
    if helper is None:
        pytest.skip("mutate helper not built — set LARES_HELPER_PATH or run from a wheel install")
    if not _akonadi_up():
        pytest.skip("akonadi not running — bug only reproduces on the async fetch path")

    async with Mutate.from_command([str(helper), "--max-body-bytes", "1024"]) as m:
        for n in range(3):
            with pytest.raises(MutateError) as exc_info:
                await m.fetch(999_999_999)
            err = exc_info.value
            assert "closed stdout" not in str(err), f"helper exited after op {n + 1}: {err}"
            assert err.code == "not_found", (
                f"unexpected error code on op {n + 1}: {err.code} — full message: {err}"
            )
