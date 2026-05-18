# Lares

Local-first AI agents for the Linux desktop. KMail (Akonadi) triage and a KRunner LLM action (planned), built on [Ollama](https://ollama.com).

> **Status: v0.1 in progress.** The KMail triage agent is the first surface; KRunner follows.

## What Lares is — and is not

Lares is a curated, opinionated **bundle** of local-first agents for KDE Plasma 6, named after the Roman *Lares* — household guardian spirits, each specialized for one part of the home. Day-one surfaces:

- **`lares.kmail`** — Akonadi triage agent (`systemd --user` service) that classifies and tags incoming mail.
- **`lares.krunner`** — KRunner LLM action (planned).

Lares is **not** a chat UI, an agent framework, or a cloud-AI bridge. Inference runs on your machine, against your local Ollama. Nothing leaves the host except calls to `localhost` and to the services you have already configured (your own IMAP / Akonadi).

## Day-one scope

1. KMail (Akonadi) triage agent.
2. KRunner LLM action (planned, not yet implemented).

Other surfaces (calendar, file triage, voice, additional mail backends, web UIs) are deliberately out of scope until v0.1 ships and has been dogfooded.

## Stack

- Python 3.12+, managed with [`uv`](https://github.com/astral-sh/uv).
- Both agents run as `systemd --user` services. KMail triage watches Akonadi via a small C++/Qt6 helper.
- LLM backend: Ollama at `http://127.0.0.1:11434`. Bring your own model — the default is `qwen3:4b-instruct-2507-q4_K_M`.

## Hard rules

- **Local-first, non-negotiable.** No cloud fallback. No telemetry. No analytics SDK.
- **No personal data leaves the machine.** The only network calls Lares makes by default are to `localhost` (Ollama) and to your own configured services.
- **No bundled models.** You bring your own Ollama install and pull your own weights.

## Install (Arch / KDE Plasma 6)

System prerequisites (build-time + runtime):

```bash
sudo pacman -S --needed base-devel cmake ninja extra-cmake-modules
# These are already installed on any Plasma 6 desktop: kf6-akonadi qt6-base
```

Install Lares (builds the C++ helpers as part of the wheel):

```bash
uv tool install lares
```

Set up config and the systemd unit:

```bash
lares install config                          # writes ~/.config/lares/config.toml skeleton
lares install systemd --enable --start        # writes unit, enables, starts
lares install check                           # pass/fail preflight
lares kmail status                            # confirm running
```

If `lares install check` reports the Ollama model isn't pulled:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

## Configuration

Single TOML file at `~/.config/lares/config.toml`. Override defaults by editing in place. The skeleton ships with sensible defaults; the most common changes are:

- `[lares.ollama].model` — swap to a smaller (`qwen3:1.7b-instruct-2507-q4_K_M`) or larger (`llama3.1:8b-instruct-q4_K_M`) model.
- `[kmail.tags]` — change the human-readable descriptions to retune classification.
- `[kmail].min_confidence` — raise to 0.7 if you'd rather see more `lares-unclassified` than wrong tags.

**Avoid models** marked `*-thinking-*` (Qwen3 thinking variants) and any `deepseek-r1:*` — they emit reasoning preambles that break JSON-mode output.

## Day-to-day commands

- `lares kmail status` — service state, queue depth, last seen item.
- `lares kmail retag <item-id>` — force re-classification of one message.
- `lares kmail retag <item-id> --remove` — strip all `lares-*` tags from one message.
- `lares install check` — composite preflight any time something feels off.

## Known v0.1 limitations

- **No bulk backfill / startup catchup.** The `lares-akonadi-mutate` helper exposes `fetch` and `set_tags` only — no bulk discovery op. `lares kmail backfill` and `lares kmail catchup` are stubbed with an actionable message; they'll work in v0.2. Mail that arrives while the service is *down* is not retroactively processed; use `lares kmail retag` per-item.
- **Single-Akonadi-instance only.** Sharing the same Akonadi DB across two machines (e.g. via `kdesync`) re-runs classification on each machine.
- **`lares install check`** can't probe Akonadi when KMail hasn't been started at least once (Akonadi is started on demand). Open KMail once after install.

## Troubleshooting

| Symptom | Check |
|---|---|
| `lares install check` says Ollama unreachable | `systemctl --user start ollama` (if you installed it as a user service) or `systemctl start ollama` |
| `lares install check` says model not pulled | `ollama pull <model>` — copy from the error message |
| Tags appear in KMail but classification is wrong | Adjust `[kmail.tags]` descriptions in config; restart the service: `systemctl --user restart lares-kmail` |
| Service won't start | `journalctl --user -u lares-kmail -e` |
| Mail stays `lares-pending` forever | Ollama is probably down. Service auto-retries with exponential backoff up to 10 attempts, then flips to `lares-error`. |

## License

[MIT](./LICENSE).
