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
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import NoReturn

import httpx

from lares.kmail import service
from lares.kmail.classifier import Classifier
from lares.kmail.config import LaresConfig, load_config
from lares.kmail.mutate import Mutate
from lares.kmail.service import _classify_and_apply  # pyright: ignore[reportPrivateUsage]
from lares.kmail.state import State
from lares.kmail.tags import LARES_PENDING

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


def _cmd_kmail_backfill(ns: argparse.Namespace) -> int:
    cfg = _load(ns)
    _setup_logging(cfg.lares.log_level)
    asyncio.run(_run_backfill(cfg, limit=ns.limit, collection=ns.collection, dry_run=ns.dry_run))
    return 0


def _cmd_kmail_catchup(ns: argparse.Namespace) -> int:
    cfg = _load(ns)
    _setup_logging(cfg.lares.log_level)
    asyncio.run(_run_catchup(cfg, since=ns.since))
    return 0


def _cmd_kmail_retag(ns: argparse.Namespace) -> int:
    cfg = _load(ns)
    _setup_logging(cfg.lares.log_level)
    asyncio.run(_run_retag(cfg, item_id=ns.item_id, remove=ns.remove))
    return 0


def _cmd_kmail_purge(ns: argparse.Namespace) -> int:
    if not ns.confirm:
        sys.stderr.write("refusing without --confirm\n")
        return 1
    cfg = _load(ns)
    db = Path(cfg.kmail.state_db_path)
    if db.exists():
        db.unlink()
    return 0


def _cmd_install_config(ns: argparse.Namespace) -> int:
    target = Path(ns.config)
    if target.exists() and not ns.force:
        sys.stderr.write(f"refusing to overwrite existing {target} (use --force)\n")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    template = resources.files("lares._config").joinpath("config.toml.skel").read_text()
    target.write_text(template)
    sys.stdout.write(f"wrote {target}\n")
    return 0


def _user_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _systemctl(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=False,
        capture_output=True,
    )


def _cmd_install_systemd(ns: argparse.Namespace) -> int:
    unit_dir = _user_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "lares-kmail.service"

    if ns.uninstall:
        if unit_path.exists():
            _systemctl("stop", "lares-kmail.service")
            _systemctl("disable", "lares-kmail.service")
            unit_path.unlink()
        _systemctl("daemon-reload")
        sys.stdout.write(f"removed {unit_path}\n")
        return 0

    template = resources.files("lares._systemd").joinpath("lares-kmail.service").read_text()
    unit_path.write_text(template)
    sys.stdout.write(f"wrote {unit_path}\n")
    _systemctl("daemon-reload")
    if ns.enable:
        _systemctl("enable", "lares-kmail.service")
    if ns.start:
        _systemctl("start", "lares-kmail.service")
    return 0


async def _run_backfill(
    cfg: LaresConfig,
    *,
    limit: int,
    collection: str | None,
    dry_run: bool,
) -> None:
    # Backfill enumerates items in the inbox(es) via the mutate helper.
    # The mutate helper does not yet expose a `list_items` op in v0.1 — see
    # design spec §13 risks. For v0.1, the CLI emits an actionable
    # "not yet implemented" message instead of pretending it works.
    sys.stderr.write(
        "backfill: requires a mutate-helper `list_items` op which is not in v0.1.\n"
        "  Tracked as v0.2 follow-up. Use KMail's UI or `lares kmail retag <id>`.\n"
    )


async def _run_catchup(
    cfg: LaresConfig,
    *,
    since: int | None,
) -> None:
    # Same caveat as backfill — requires a mutate `list_items` op.
    sys.stderr.write(
        "catchup: requires a mutate-helper `list_items` op which is not in v0.1.\n"
        "  Tracked as v0.2 follow-up.\n"
    )


async def _run_retag(cfg: LaresConfig, *, item_id: int, remove: bool) -> None:
    state = State(cfg.kmail.state_db_path)
    try:
        async with (
            Mutate.from_config(cfg) as mutate,
            Classifier(cfg) as classifier,
        ):
            if remove:
                await mutate.set_tags(item_id, [])
                return
            await mutate.set_tags(item_id, [LARES_PENDING])
            state.record_pending(item_id)
            fr = await mutate.fetch(item_id)
            await _classify_and_apply(
                fr,
                mutate,
                classifier,
                state,
                max_retries=cfg.kmail.max_retries,
            )
    finally:
        state.close()


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

    backfill = kmail_sub.add_parser("backfill", help="batch-tag existing untagged inbox items")
    backfill.add_argument("--limit", type=int, default=100)
    backfill.add_argument("--collection", default=None)
    backfill.add_argument("--dry-run", action="store_true")
    backfill.set_defaults(func=_cmd_kmail_backfill)

    catchup = kmail_sub.add_parser("catchup", help="process inbox items newer than last seen")
    catchup.add_argument("--since", type=int, default=None)
    catchup.set_defaults(func=_cmd_kmail_catchup)

    retag = kmail_sub.add_parser("retag", help="force re-classification of one item")
    retag.add_argument("item_id", type=int)
    retag.add_argument(
        "--remove",
        action="store_true",
        help="strip all lares-* tags from the item instead",
    )
    retag.set_defaults(func=_cmd_kmail_retag)

    purge = kmail_sub.add_parser("purge", help="delete sqlite state (destructive)")
    purge.add_argument("--confirm", action="store_true", required=True)
    purge.set_defaults(func=_cmd_kmail_purge)

    install = sub.add_parser("install", help="install lifecycle (config / systemd / check)")
    install_sub = install.add_subparsers(dest="install_cmd", required=True)

    install_cfg = install_sub.add_parser("config", help="write config.toml skeleton")
    install_cfg.add_argument(
        "--force", action="store_true", help="overwrite an existing config file"
    )
    install_cfg.set_defaults(func=_cmd_install_config)

    install_sd = install_sub.add_parser(
        "systemd",
        help="install / enable / start the systemd --user unit",
    )
    install_sd.add_argument("--enable", action="store_true")
    install_sd.add_argument("--start", action="store_true")
    install_sd.add_argument(
        "--uninstall",
        action="store_true",
        help="stop, disable, and remove the unit",
    )
    install_sd.set_defaults(func=_cmd_install_systemd)

    return parser


def main(argv: list[str] | None = None) -> NoReturn:
    parser = build_parser()
    ns = parser.parse_args(argv)
    rc = int(ns.func(ns))
    raise SystemExit(rc)


if __name__ == "__main__":  # pragma: no cover
    main()
