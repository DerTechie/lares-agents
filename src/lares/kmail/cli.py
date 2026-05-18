# SPDX-License-Identifier: MIT
"""`lares` CLI entry point.

argparse-based. One top-level dispatcher with `kmail` and `install`
subcommand groups. Each subcommand binds an `_cmd_*` function via
`set_defaults(func=...)` so the dispatcher is a one-liner.

Tasks 15-22 extend this file; Task 14 lays down the run-only skeleton.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import NoReturn

from lares.kmail import service
from lares.kmail.config import LaresConfig, load_config

logger = logging.getLogger(__name__)


def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "lares" / "config.toml"


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _load(ns: argparse.Namespace) -> LaresConfig:
    return load_config(ns.config)


def _cmd_kmail_run(ns: argparse.Namespace) -> int:
    cfg = _load(ns)
    _setup_logging(cfg.lares.log_level)
    try:
        asyncio.run(service.run(cfg))
    except KeyboardInterrupt:
        return 0
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lares")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="path to config.toml (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    kmail = sub.add_parser("kmail", help="KMail/Akonadi triage agent commands")
    kmail_sub = kmail.add_subparsers(dest="kmail_cmd", required=True)

    run = kmail_sub.add_parser("run", help="run the triage service (foreground)")
    run.set_defaults(func=_cmd_kmail_run)

    return parser


def main(argv: list[str] | None = None) -> NoReturn:
    parser = build_parser()
    ns = parser.parse_args(argv)
    rc = int(ns.func(ns))
    raise SystemExit(rc)


if __name__ == "__main__":  # pragma: no cover
    main()
