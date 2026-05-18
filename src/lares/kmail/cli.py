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
import json
import logging
import os
import sys
from pathlib import Path
from typing import NoReturn

import httpx

from lares.kmail import service
from lares.kmail.config import LaresConfig, load_config
from lares.kmail.state import State

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


def _cmd_kmail_status(ns: argparse.Namespace) -> int:
    cfg = _load(ns)
    state = State(cfg.kmail.state_db_path)
    try:
        depth = state.queue_depth()
        max_id = state.max_item_id()
    finally:
        state.close()
    report: dict[str, object] = {
        "queue_depth": depth,
        "last_seen_item_id": max_id,
        "state_db_path": str(cfg.kmail.state_db_path),
    }
    if getattr(ns, "json", False):
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"lares kmail status\n"
            f"  state db: {report['state_db_path']}\n"
            f"  queue depth: {depth}\n"
            f"  last seen item id: {max_id}\n"
        )
    return 0


def _cmd_kmail_config_check(ns: argparse.Namespace) -> int:
    cfg = _load(ns)
    fails: list[str] = []
    try:
        with httpx.Client(base_url=cfg.lares.ollama.endpoint, timeout=5.0) as client:
            resp = client.get("/api/tags")
            resp.raise_for_status()
            available = {m.get("name") for m in resp.json().get("models", [])}
            if cfg.lares.ollama.model not in available:
                fails.append(
                    f'Ollama model "{cfg.lares.ollama.model}" not pulled.\n'
                    f"  Fix:  ollama pull {cfg.lares.ollama.model}"
                )
    except httpx.HTTPError as exc:
        fails.append(f"Ollama not reachable at {cfg.lares.ollama.endpoint}: {exc}")

    if fails:
        for msg in fails:
            sys.stdout.write(f"✗ {msg}\n")
        return 1
    sys.stdout.write("✓ config valid; ollama reachable; model pulled.\n")
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

    status = kmail_sub.add_parser("status", help="print service state")
    status.add_argument("--json", action="store_true", help="emit JSON instead of text")
    status.set_defaults(func=_cmd_kmail_status)

    cfg_check = kmail_sub.add_parser("config-check", help="validate config + preflight")
    cfg_check.set_defaults(func=_cmd_kmail_config_check)

    return parser


def main(argv: list[str] | None = None) -> NoReturn:
    parser = build_parser()
    ns = parser.parse_args(argv)
    rc = int(ns.func(ns))
    raise SystemExit(rc)


if __name__ == "__main__":  # pragma: no cover
    main()
