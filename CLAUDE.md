# CLAUDE.md — lares-agents

> Per-repo brief. The binding project brief lives in the **private overlord repo** `DerTechie/lares` — strategy, hard rules, GTM, decisions. If you are working on this code repo and have access to the overlord, read its [`CLAUDE.md`](https://github.com/DerTechie/lares) first. If you do not have access, this file is the public-facing subset.

---

## What this repo is

The single public Python project that implements the Lares agents. Internal module layout (planned — modules land as features arrive, not before):

- `lares.kmail` — Akonadi triage agent (`systemd --user` service, D-Bus to Akonadi).
- `lares.krunner` — KRunner LLM action, shipped as a long-running `systemd --user` D-Bus daemon speaking `org.kde.krunner1`. KRunner discovers it via a `.service` + `.desktop` pair; there is no separate compiled plugin. Python cannot host a first-class KRunner `KPlugin` — this is a known tradeoff.
- `lares.core` — shared Ollama client, config loader, logging.
- `lares.cli` — `lares` CLI for inspection, agent control, debugging.

Monorepo until size or coupling forces a split. A second concrete implementation must exist before introducing abstractions.

---

## Hard rules

- **Local-first, non-negotiable.** No cloud endpoints in source. Hardcoded URLs must be `http://127.0.0.1:11434` (Ollama) or `localhost` variants. External endpoints come from user config only — never from defaults.
- **No telemetry, no analytics, no "phone home."** Logging goes to stdout / `journalctl`. No HTTP calls to anything outside what the user has configured.
- **No bundled model weights.** Users pull their own models. The code declares which models it has been tested with; it does not ship binaries.
- **D-Bus is the IPC.** Akonadi and KRunner integration use D-Bus. No invented IPC, no socket-based shims unless D-Bus genuinely cannot do it.
- **No personal data in test fixtures.** Synthetic mail / synthetic input only. CI must never see a real mailbox.
- **Python 3.12+, `uv` for deps, `ruff` for lint, `pytest` for tests.** Lockfile committed.

---

## Working style

- Plain modules; no plugin systems, no backend abstractions, no agent registries until a second concrete implementation exists.
- Long-running agents are `systemd --user` services. On-demand surfaces are short-lived scripts.
- Single user config at `~/.config/lares/config.toml`, with per-agent `[<agent>]` sections.
- Degrade gracefully when Ollama is unreachable or the configured model is missing.
- License headers / SPDX tags on every source file.

---

## What does *not* belong here

- Strategy, brand, GTM, monetization, prior-art landscape, build-in-public artifacts — those live in the private overlord.
- Workstation bootstrap (Ollama install, default model pulls, system packages) — that lives in [`DerTechie/dotfiles`](https://github.com/DerTechie/dotfiles).
- Infrastructure (Terraform, hosting) and the marketing site — separate repos, planned but not yet introduced.
