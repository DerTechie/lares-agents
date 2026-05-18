# Lares

Local-first AI agents for the Linux desktop. KMail (Akonadi) triage and a KRunner LLM action, built on [Ollama](https://ollama.com).

> **Status: scaffolding.** No agents are functional yet. This repository will hold the agent implementations as they land.

## What Lares is — and is not

Lares is a curated, opinionated **bundle** of local-first agents for KDE Plasma 6, named after the Roman *Lares* — household guardian spirits, each specialized for one part of the home. Day-one surfaces:

- **`lares.kmail`** — Akonadi triage agent (`systemd --user` service) that classifies and tags incoming mail.
- **`lares.krunner`** — KRunner LLM action that turns natural-language input into an answer or action.

Lares is **not** a chat UI, an agent framework, or a cloud-AI bridge. Inference runs on your machine, against your local Ollama. Nothing leaves the host except calls to `localhost` and to the services you have already configured (your own IMAP / Akonadi).

## Day-one scope

1. KMail (Akonadi) triage agent.
2. KRunner LLM action.

Other surfaces (calendar, file triage, voice, additional mail backends, web UIs) are deliberately out of scope until v0.1 ships and has been dogfooded.

## Stack

- Python 3.12+, managed with [`uv`](https://github.com/astral-sh/uv).
- Long-running agents as `systemd --user` services. On-demand agents as short-lived scripts invoked by a host shim.
- D-Bus for KMail (Akonadi) and KRunner integration.
- LLM backend: Ollama at `http://127.0.0.1:11434`. Bring your own model.

## Hard rules

- **Local-first, non-negotiable.** No cloud fallback. No telemetry. No analytics SDK.
- **No personal data leaves the machine.** The only network calls Lares makes by default are to `localhost` (Ollama) and to your own configured services.
- **No bundled models.** You bring your own Ollama install and pull your own weights.

## Install

Not ready yet. When it is, the companion [`DerTechie/dotfiles`](https://github.com/DerTechie/dotfiles) Arch + KDE bootstrap will install Lares as part of the workstation setup. A distro-agnostic install script will follow.

## License

[MIT](./LICENSE).
