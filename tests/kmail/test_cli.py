# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from lares.kmail.cli import build_parser, default_config_path


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
