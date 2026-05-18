# SPDX-License-Identifier: MIT
from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_httpx import HTTPXMock

from lares.kmail.cli import (
    _cmd_kmail_config_check,  # pyright: ignore[reportPrivateUsage]
    _cmd_kmail_status,  # pyright: ignore[reportPrivateUsage]
    build_parser,
    default_config_path,
)
from lares.kmail.config import KMailConfig, LaresConfig, LaresShared, OllamaConfig
from lares.kmail.state import State


def test_default_config_path_under_home() -> None:
    p = default_config_path()
    assert p.name == "config.toml"
    assert "lares" in p.parts


def test_parser_dispatches_kmail_run() -> None:
    parser = build_parser()
    ns = parser.parse_args(["kmail", "run"])
    assert ns.func.__name__ == "_cmd_kmail_run"


def test_parser_unknown_subcommand_exits() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["totally-unknown"])


def _make_cfg(tmp_path: Path) -> LaresConfig:
    return LaresConfig(
        lares=LaresShared(log_level="INFO", ollama=OllamaConfig(model="m")),
        kmail=KMailConfig(
            state_db_path=tmp_path / "state.db",
            tags={"personal": "x", "business": "x", "newsletter": "x", "notification": "x"},
        ),
    )


def test_status_reports_queue_depth(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _make_cfg(tmp_path)
    st = State(cfg.kmail.state_db_path)
    st.record_pending(1)
    st.enqueue_retry(1, reason="x")
    st.close()

    class _NS:
        config = tmp_path / "config.toml"
        json = False

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(_cfg_toml(cfg))
    rc = _cmd_kmail_status(_NS())  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert rc == 0
    assert "queue depth: 1" in out


def test_status_json_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _make_cfg(tmp_path)
    State(cfg.kmail.state_db_path).close()

    class _NS:
        config = tmp_path / "config.toml"
        json = True

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(_cfg_toml(cfg))
    rc = _cmd_kmail_status(_NS())  # type: ignore[arg-type]
    out = capsys.readouterr().out
    payload = _json.loads(out)
    assert rc == 0
    assert payload["queue_depth"] == 0


@pytest.mark.asyncio
async def test_config_check_passes(
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = _make_cfg(tmp_path)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(_cfg_toml(cfg))
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/tags",
        json={"models": [{"name": "m"}]},
    )

    class _NS:
        config = cfg_file

    rc = _cmd_kmail_config_check(_NS())  # type: ignore[arg-type]
    assert rc == 0


@pytest.mark.asyncio
async def test_config_check_reports_missing_model(
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = _make_cfg(tmp_path)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(_cfg_toml(cfg))
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/tags",
        json={"models": [{"name": "different"}]},
    )

    class _NS:
        config = cfg_file

    rc = _cmd_kmail_config_check(_NS())  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert rc != 0
    assert "ollama pull m" in out


def _cfg_toml(cfg: LaresConfig) -> str:
    """Render a minimal TOML for the cfg the unit test built in-process."""
    return f"""
[lares.ollama]
model = "{cfg.lares.ollama.model}"
endpoint = "{cfg.lares.ollama.endpoint}"

[kmail]
state_db_path = "{cfg.kmail.state_db_path}"

[kmail.tags]
personal = "x"
business = "x"
newsletter = "x"
notification = "x"
"""
