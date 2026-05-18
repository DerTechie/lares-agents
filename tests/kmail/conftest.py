# SPDX-License-Identifier: MIT
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session", autouse=True)
def _materialize_systemd_unit() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Ensure the systemd unit file is reachable via importlib.resources during tests.

    scikit-build-core editable installs do not run CMake's install step, so the
    unit file that lands in the wheel at lares/_systemd/lares-kmail.service is
    missing from the source tree's src/lares/_systemd/ in `uv sync` mode. Copy
    it from packaging/systemd/ for the duration of the test session, then
    remove it on teardown so the source tree stays clean.
    """
    src = (
        Path(__file__).resolve().parent.parent.parent
        / "packaging"
        / "systemd"
        / "lares-kmail.service"
    )
    dst = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "lares"
        / "_systemd"
        / "lares-kmail.service"
    )
    created = False
    if not dst.exists():
        shutil.copyfile(src, dst)
        created = True
    try:
        yield
    finally:
        if created:
            dst.unlink(missing_ok=True)
