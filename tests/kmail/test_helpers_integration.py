# SPDX-License-Identifier: MIT
"""Integration tests for the C++ helpers against a real (sandboxed) Akonadi.

These tests require a running Akonadi server with the maildir resource
configured against a test directory. Run manually:

    pytest -m integration tests/kmail/test_helpers_integration.py

Skipped automatically if `qdbus6 org.freedesktop.Akonadi` reports
unreachable.
"""

from __future__ import annotations

import subprocess
from importlib import resources
from pathlib import Path

import pytest

from lares.kmail.mutate import Mutate, MutateError


def _akonadi_up() -> bool:
    try:
        r = subprocess.run(
            ["qdbus6", "org.freedesktop.Akonadi"],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return False
    return r.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _akonadi_up(), reason="akonadi not running"),
]


@pytest.mark.asyncio
async def test_mutate_helper_starts_and_responds_to_fetch_unknown() -> None:
    """Smoke test: helper binary launches, accepts JSON on stdin, returns error
    for an unknown item_id. Validates the wire protocol end-to-end."""
    helper = Path(str(resources.files("lares") / "_bin" / "lares-akonadi-mutate"))
    if not helper.exists():
        pytest.skip("mutate helper not built")
    async with Mutate.from_command([str(helper), "--max-body-bytes", "1024"]) as m:
        with pytest.raises(MutateError) as ei:
            await m.fetch(99999999)
        assert ei.value.code == "not_found"
