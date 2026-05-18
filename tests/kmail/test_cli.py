# SPDX-License-Identifier: MIT
from __future__ import annotations

import json as _json
import os
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_httpx import HTTPXMock

from lares.kmail.cli import (
    _cmd_install_check,  # pyright: ignore[reportPrivateUsage]
    _cmd_install_config,  # pyright: ignore[reportPrivateUsage]
    _cmd_install_systemd,  # pyright: ignore[reportPrivateUsage]
    _cmd_kmail_config_check,  # pyright: ignore[reportPrivateUsage]
    _cmd_kmail_purge,  # pyright: ignore[reportPrivateUsage]
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


def test_parser_dispatches_kmail_backfill() -> None:
    parser = build_parser()
    ns = parser.parse_args(["kmail", "backfill", "--limit", "5", "--dry-run"])
    assert ns.func.__name__ == "_cmd_kmail_backfill"
    assert ns.limit == 5
    assert ns.dry_run is True


def test_parser_dispatches_kmail_catchup() -> None:
    parser = build_parser()
    ns = parser.parse_args(["kmail", "catchup", "--since", "42"])
    assert ns.func.__name__ == "_cmd_kmail_catchup"
    assert ns.since == 42


def test_parser_dispatches_kmail_retag() -> None:
    parser = build_parser()
    ns = parser.parse_args(["kmail", "retag", "42", "--remove"])
    assert ns.func.__name__ == "_cmd_kmail_retag"
    assert ns.item_id == 42
    assert ns.remove is True


def test_parser_dispatches_kmail_purge_requires_confirm() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["kmail", "purge"])  # missing --confirm


def test_kmail_purge_removes_sqlite(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    db = tmp_path / "state.db"
    cfg_file.write_text(
        f"""
[lares.ollama]
model = "m"

[kmail]
state_db_path = "{db}"

[kmail.tags]
personal = "x"
business = "x"
newsletter = "x"
notification = "x"
"""
    )
    State(db).close()
    assert db.exists()

    class _NS:
        config = cfg_file
        confirm = True

    rc = _cmd_kmail_purge(_NS())  # type: ignore[arg-type]
    assert rc == 0
    assert not db.exists()


def test_install_config_writes_skeleton_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"

    class _NS:
        config = target
        force = False

    rc = _cmd_install_config(_NS())  # type: ignore[arg-type]
    assert rc == 0
    assert target.exists()
    body = target.read_text()
    assert "[lares.ollama]" in body
    assert "qwen3:4b-instruct-2507-q4_K_M" in body


def test_install_config_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("existing")

    class _NS:
        config = target
        force = False

    rc = _cmd_install_config(_NS())  # type: ignore[arg-type]
    assert rc != 0
    assert target.read_text() == "existing"


def test_install_config_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("existing")

    class _NS:
        config = target
        force = True

    rc = _cmd_install_config(_NS())  # type: ignore[arg-type]
    assert rc == 0
    assert "qwen3" in target.read_text()


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


def _systemd_unit_dir(home: Path) -> Path:
    return home / ".config" / "systemd" / "user"


def test_install_systemd_writes_unit_to_user_dir(tmp_path: Path) -> None:
    home = tmp_path / "home"
    unit_dir = _systemd_unit_dir(home)

    class _NS:
        config = tmp_path / "config.toml"
        enable = False
        start = False
        uninstall = False

    with patch.dict(os.environ, {"HOME": str(home)}), patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        rc = _cmd_install_systemd(_NS())  # type: ignore[arg-type]
    assert rc == 0
    unit = unit_dir / "lares-kmail.service"
    assert unit.exists()
    assert "Description=Lares" in unit.read_text()
    # daemon-reload always
    assert any("daemon-reload" in str(c.args) for c in mock_run.call_args_list)


def test_install_systemd_with_enable_and_start(tmp_path: Path) -> None:
    home = tmp_path / "home"

    class _NS:
        config = tmp_path / "config.toml"
        enable = True
        start = True
        uninstall = False

    with patch.dict(os.environ, {"HOME": str(home)}), patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        rc = _cmd_install_systemd(_NS())  # type: ignore[arg-type]
    assert rc == 0
    calls = [str(c.args[0]) for c in mock_run.call_args_list]
    assert any("enable" in s for s in calls)
    assert any("start" in s for s in calls)


def test_install_systemd_uninstall_removes_unit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    unit_dir = _systemd_unit_dir(home)
    unit_dir.mkdir(parents=True)
    (unit_dir / "lares-kmail.service").write_text("stub")

    class _NS:
        config = tmp_path / "config.toml"
        enable = False
        start = False
        uninstall = True

    with patch.dict(os.environ, {"HOME": str(home)}), patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        rc = _cmd_install_systemd(_NS())  # type: ignore[arg-type]
    assert rc == 0
    assert not (unit_dir / "lares-kmail.service").exists()


def test_install_check_reports_all_pass(
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "m"

[kmail.tags]
personal = "x"
business = "x"
newsletter = "x"
notification = "x"
"""
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/tags",
        json={"models": [{"name": "m"}]},
    )
    # Skip the helper-presence and akonadi-up checks via env override.
    with patch.dict(os.environ, {"LARES_CHECK_SKIP": "helpers,akonadi,systemd"}):

        class _NS:
            config = cfg_file

        rc = _cmd_install_check(_NS())  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert rc == 0
    assert "✓ ollama" in out.lower()
    assert "✓ config" in out.lower()
