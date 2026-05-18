# `lares.kmail` — Akonadi triage agent (v0.1) — design spec

**Status:** approved for implementation
**Date:** 2026-05-18
**Author:** Mike Esser
**Repo:** `DerTechie/lares-agents`

## 1. Purpose

A local-first, headless `systemd --user` service that watches the user's inbox(es) over Akonadi and applies a small set of Akonadi tags to incoming mail (`personal`, `business`, `newsletter`, `notification`) based on a local Ollama classification call. Reversible (tags only, no folder moves), conservative (low-confidence verdicts get a `lares-unclassified` fallback), and resilient (Ollama-down items get a visible `lares-pending` tag plus a sqlite-backed retry queue).

The user's stated motivation: scan past newsletter clutter quickly and have business inquiries leap out.

## 2. Scope

### In scope (v0.1)

- One systemd `--user` service (`lares-kmail.service`).
- Auto-detected inbox-like collections (multi-account aware via Akonadi `SpecialCollectionAttribute("inbox")`).
- 4-way classification driven by config-defined tag taxonomy.
- `lares-pending`, `lares-unclassified`, `lares-error` namespaced control tags.
- Retry queue with exponential backoff, persisted to sqlite.
- `lares` CLI: service entry point, backfill, retag, catchup, status, config-check, install lifecycle.
- Self-contained install lifecycle in this repo (systemd unit ship & install, config skeleton, preflight checks).
- Two small C++/Qt6 helpers (`lares-akonadi-notify`, `lares-akonadi-mutate`) shipped inside the wheel, built by `scikit-build-core` at install time.
- Unit + integration tests; synthetic `.eml` fixtures; CI builds the C++ helpers on every PR.

### Out of scope (explicit non-goals)

- Folder moves / filing. Tag-only. KMail's own filter rules can translate tags → moves if the user wants.
- Re-classification on tag change or model change.
- User-correction feedback loop / personalized classifier.
- Multi-account configuration UI; per-account taxonomy overrides.
- Calendar, contacts, non-mail Akonadi data.
- Web UI, system tray, KCM module.
- Body summarization or extraction beyond classification.
- Any telemetry, metrics export, or analytics.

## 3. Architecture

```
                          ┌──────────────────────────────┐
                          │  Akonadi server (kf6)        │
                          │  - binary protocol socket    │
                          │  - org.freedesktop.Akonadi…  │
                          └──────────────────────────────┘
                                ▲             ▲
                  Akonadi::Monitor      Akonadi::ItemModifyJob
                                │             │
            ┌─────────────────────────────┐  ┌─────────────────────────────┐
            │ lares-akonadi-notify (C++)  │  │ lares-akonadi-mutate (C++)  │
            │ subprocess, NDJSON → stdout │  │ subprocess, JSON ⇄ stdio    │
            └─────────────────────────────┘  └─────────────────────────────┘
                          ▲                              ▲
                          │ stdout pipe                  │ stdin/stdout pipes
                          │                              │
                ┌────────────────────────────────────────────────┐
                │ lares.kmail.service  (Python 3.12, asyncio)    │
                │  - reads notify events                          │
                │  - applies lares-pending tag immediately        │
                │  - classifies via Ollama (httpx.AsyncClient)    │
                │  - replaces pending with verdict tag            │
                │  - persists pending queue + retry state         │
                └────────────────────────────────────────────────┘
                          │                              ▲
                          ▼                              │
                ┌──────────────────────┐      ┌──────────────────────┐
                │ Ollama 127.0.0.1:11434│      │ ~/.local/state/lares/│
                │  /api/generate         │      │   kmail.db (sqlite)  │
                └──────────────────────┘      └──────────────────────┘
```

### Invariants

- The two C++ helpers are the **only** code that links against `KPim6::AkonadiCore`. They are stateless, narrow, and ignorant of LLMs, tag semantics, queues, or policy.
- The Python service owns all policy: what to tag, when to retry, what constitutes pending, what to classify.
- One systemd `--user` service supervises both C++ subprocesses (restart on exit) and the asyncio main loop.

### Why Akonadi mutation requires C++

Verified via research pass on 2026-05-18:

- **`akonadiclient`** is not packaged on Arch (core, extra, or AUR — 0 hits), AND its `tags` subcommand cannot apply tags to items even where built — it manages tag *definitions* only.
- **PyKF6 / Python bindings to Akonadi do not exist** in the KF6 timeline. PyKDE4's `PyKDE4.akonadi` is Qt4-defunct.
- **KMail's `org.kde.kmail` D-Bus interface** operates on KMail's in-memory state and requires the KMail UI to be running — incompatible with headless triage.
- **Akonadi's notification stream** rides its private binary protocol over a Unix socket, not D-Bus. The D-Bus `NotificationManager` configures filters and returns a `NotificationSource` path; actual change events flow on a separate socket. Reimplementing the binary protocol in Python is a non-trivial project.

Conclusion: no pure-Python path exists in 2026 for headless Akonadi mutation and notification. The smallest workable surface area is ~300 LoC of Qt6/AkonadiCore in two single-file helpers. This is consistent with CLAUDE.md's clause: *"no socket-based shims unless D-Bus genuinely cannot do it."*

## 4. Build & packaging

### Build backend

Switch from `hatchling` to **`scikit-build-core`**. Modern PEP 517 backend that runs CMake during `pip install` / `uv build` / `uv sync`. Industry-standard for Python packages shipping native code.

### Repo layout

```
lares-agents/
├── pyproject.toml                  # build-backend = scikit-build-core
├── CMakeLists.txt                  # top-level: builds Python pkg + C++ binaries
├── src/lares/
│   ├── __init__.py
│   ├── _bin/                       # populated at build time by CMake install(TARGETS)
│   ├── _config/
│   │   └── config.toml.skel
│   ├── _systemd/
│   │   └── lares-kmail.service
│   └── kmail/
│       ├── __init__.py
│       ├── service.py
│       ├── notify.py
│       ├── mutate.py
│       ├── classifier.py
│       ├── state.py
│       ├── config.py
│       ├── tags.py
│       └── cli.py
├── src/akonadi_bridge/
│   ├── CMakeLists.txt
│   ├── notify.cpp
│   └── mutate.cpp
├── packaging/systemd/
│   └── lares-kmail.service         # source of truth; copied into src/lares/_systemd/ by build
└── tests/kmail/
    ├── conftest.py
    ├── test_config.py
    ├── test_state.py
    ├── test_classifier.py
    ├── test_notify.py
    ├── test_mutate.py
    ├── test_service.py
    ├── test_cli.py
    ├── test_tags.py
    └── fixtures/
        ├── personal.eml
        ├── business.eml
        ├── newsletter.eml
        └── notification.eml
```

CMake installs binaries inside the wheel under the `lares` package:

```cmake
install(TARGETS lares-akonadi-notify lares-akonadi-mutate
        RUNTIME DESTINATION lares/_bin)
```

Python resolves binaries via `importlib.resources.files("lares") / "_bin" / "lares-akonadi-notify"`. Deterministic, no `$PATH` pollution, no separate install step. Config skeleton and systemd unit resolve the same way.

### `[project.scripts]`

```toml
[project.scripts]
lares = "lares.kmail.cli:main"
```

Promoted to a dispatcher when the second agent (KRunner) lands.

### Build-time deps (user machine)

- `cmake`, `ninja`, C++17 compiler — `base-devel` on Arch
- `extra-cmake-modules`
- `kpim6-akonadi`, `kpim6-mime`, `qt6-base` — present on any Plasma 6 desktop with KDE PIM 6 installed

Documented in README. Arch one-liner: `sudo pacman -S --needed base-devel cmake ninja extra-cmake-modules`.

### CI

GitHub Actions hosted runners (currently Ubuntu Noble 24.04) ship only KDE 5 PIM packages — no `KPim6Akonadi` / `KPim6Mime` are available there. The CI job therefore runs inside an `ubuntu:25.10` container, which is the first Ubuntu release with KDE 6 PIM packaged under their non-prefixed Debian names (`libakonadi-dev`, `libkmime-dev`, both shipping `KPim6*` CMake config). `.github/workflows/ci.yml` adds:

```yaml
jobs:
  check:
    runs-on: ubuntu-latest
    container: ubuntu:25.10
    steps:
      - run: apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git
      - uses: actions/checkout@v4
      - run: apt-get install -y --no-install-recommends build-essential cmake ninja-build extra-cmake-modules qt6-base-dev libakonadi-dev libkmime-dev
      - run: uv sync     # builds C++ via scikit-build-core
```

Runs `ruff check`, `ruff format --check`, `pyright`, `pytest -m "not integration"`. Integration suite runs on `workflow_dispatch` + nightly.

## 5. C++ helper contracts

### `lares-akonadi-notify`

- **Invocation:** `lares-akonadi-notify --mimetype message/rfc822 --collection-attr inbox [--extra-collection NAME ...]`. `--extra-collection` is repeatable and defaults to empty; it widens the filter to include collections by display name even if they lack the requested `SpecialCollectionAttribute` (escape hatch for custom landing folders mentioned in §15).
- **Behavior:** instantiates `Akonadi::Monitor`, filters to `MessageMimeType("message/rfc822")` and to collections whose `SpecialCollectionAttribute::Type == "inbox"`. Auto-reconnects on Akonadi server restart — the implementation must connect to `Akonadi::ServerManager::stateChanged` and re-apply `setMimeTypeMonitored` on transitions to `Running`. (`Akonadi::Monitor` re-establishes its session internally but does not guarantee filter restoration after a server bounce.)
- **Output:** one NDJSON line per `itemAdded(Item, Collection)` signal to stdout, flushed immediately:
  ```json
  {"event":"item_added","item_id":12345,"collection_id":42,"remote_id":"<message-id>","mimetype":"message/rfc822","ts":"2026-05-18T17:42:11Z"}
  ```
- **Logging:** stderr only; systemd captures into journald.
- **Lifecycle:** runs until SIGTERM. Exits non-zero only on unrecoverable errors (e.g. Akonadi never came up).

### `lares-akonadi-mutate`

- **Invocation:** `lares-akonadi-mutate --max-body-bytes 8192` (cap is config-driven; passed at startup).
- **Protocol:** one JSON object per line in each direction over stdio. Synchronous one-in-one-out. Python serializes requests via an `asyncio.Lock`.

  **Fetch:**
  ```json
  → {"id":"req-1","op":"fetch","item_id":12345}
  ← {"id":"req-1","ok":true,"item_id":12345,
     "headers":{"From":"…","To":"…","Subject":"…","Date":"…","List-Id":"…"},
     "body_text":"…first N bytes of text/plain part…",
     "tags":["lares-pending"]}
  ```

  **Set tags (replace within `lares-*` namespace):**
  ```json
  → {"id":"req-2","op":"set_tags","item_id":12345,"tags":["personal"]}
  ← {"id":"req-2","ok":true,"item_id":12345,"tags":["personal"]}
  ```
  Semantics: replaces all `lares-*` tags on this item with the given list (auto-creating tag definitions via `TagCreateJob` if missing). **Non-`lares-*` tags the user added manually are preserved.**

- **Errors:** `{"id":"…","ok":false,"error":"…","code":"…"}`. Codes:
  - `not_found` — item id does not resolve, or item-fetch returned an empty result set.
  - `akonadi_offline` — `Akonadi::ServerManager::state() != Running` at request time. The helper probes this before issuing each fetch or modify job.
  - `bad_request` — request line is not valid JSON, is missing the `op` field, or names an unknown op.
  - `internal` — Akonadi job failed for any reason other than the above (e.g. `ItemModifyJob` or `TagCreateJob` reported an error).
- **Lifecycle:** long-running, one process for service lifetime. On crash, Python restarts and re-issues in-flight requests.

### Implementation notes

- Both helpers rely on `Akonadi::Session::defaultSession()` — they do not construct an explicit `Akonadi::Session`. Akonadi auto-creates the default session on the first job dispatch.
- `mutate` uses `Akonadi::ItemModifyJob` with `disableRevisionCheck()` (we may not have an up-to-date item revision); `setTags()` accepts the post-merge list.
- Body extraction in `fetch`: `Akonadi::ItemFetchJob` with `FetchScope().fetchFullPayload(true)`, then walk the MIME tree for the first `text/plain` part, decode quoted-printable / base64 / charset, truncate to `--max-body-bytes`.
- **HTML-only emails** (common for newsletters / marketing mail): if no `text/plain` part exists, walk for the first `text/html` part and run a minimal `QTextDocumentFragment::fromHtml(...).toPlainText()` pass to strip markup. The result is returned in the same `body_text` field — the LLM does not need to know the source. No separate field; truncation still applies to the post-strip text.
- Multipart-alternative messages: prefer `text/plain` over `text/html` when both exist.
- Empty body (rare; calendar invites etc. may have no body at all): return `body_text: ""` and let the classifier work from headers alone.

## 6. Python service architecture

### Module responsibilities

| Module | Responsibility | External deps |
|---|---|---|
| `service.py` | Sole asyncio entry point. Owns the event loop. Wires the four collaborators in one `TaskGroup`. | asyncio |
| `notify.py` | Async context manager around `lares-akonadi-notify` subprocess. Yields parsed events. | asyncio.subprocess |
| `mutate.py` | Async context manager around `lares-akonadi-mutate` subprocess. `await mutate.fetch(item_id)` / `await mutate.set_tags(item_id, tags)`. Internal lock serializes stdio. | asyncio.subprocess |
| `classifier.py` | Async `await classifier.classify(item)`. Owns one `httpx.AsyncClient`. Builds prompt from config-driven taxonomy. Parses + validates with pydantic. | httpx, pydantic |
| `state.py` | sqlite wrapper. Queue ops, item-state transitions, attempt counter, backoff calc. Synchronous (runs in default executor via `asyncio.to_thread`). | sqlite3 (stdlib) |
| `config.py` | `tomllib` load + pydantic validation. Returns a frozen dataclass. | pydantic, tomllib (stdlib) |
| `tags.py` | Namespace constants (`LARES_PENDING`, `LARES_UNCLASSIFIED`, `LARES_ERROR`), `is_lares_tag(name)` predicate. | none |
| `cli.py` | argparse-based dispatch. One `main()` entry point, one subparser per `kmail`/`install` command. | argparse (stdlib) |

### Event loop shape

```python
async def main() -> None:
    config = load_config()
    state = State(config.kmail.state_db_path)
    async with (
        Notify(config) as notify,
        Mutate(config) as mutate,
        Classifier(config) as classifier,
    ):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(consume_new_mail(notify, mutate, classifier, state))
            tg.create_task(drain_retry_queue(mutate, classifier, state))
```

Two concurrent tasks in one `TaskGroup`. Both share `mutate` and `classifier`. Cancellation on SIGTERM propagates through structured concurrency; each subprocess context-manager sends SIGTERM, waits ≤2s, SIGKILLs if needed.

### Per-message state machine

The two concurrent tasks (`consume_new_mail` and `drain_retry_queue`) share the same per-message steps from `fetch` onward but differ in how they enter:

**`consume_new_mail` (triggered by `notify` event):**

1. `notify` emits `item_added`.
2. `mutate.fetch(item_id)` — if the item already has any `lares-*` tag, **skip** (idempotency via tag presence; handles duplicate `item_added` events emitted after Akonadi restart or during catchup overlap).
3. `mutate.set_tags(item_id, ["lares-pending"])` — immediately visible in KMail.
4. `classify_and_apply(item)` (see below).

**`drain_retry_queue` (triggered by `due_at` timer or `retry_added` event):**

1. Pull next-due `item_id` from `retry_queue`.
2. `mutate.fetch(item_id)` — **does not check `lares-*` tag presence**, because `lares-pending` is exactly what we expect. If the item was deleted in the meantime (`code: not_found`), remove from queue and persist `state='error'` with `last_error='item_deleted'`.
3. `classify_and_apply(item)` (see below).

**Shared `classify_and_apply` step:**

- `classifier.classify(item)` — Ollama call with `format` schema, `temperature: 0`.
- **Verdict (confidence ≥ `min_confidence`):** `mutate.set_tags(item_id, [verdict])`; persist `state='classified'`; remove from `retry_queue` if present.
- **Low confidence:** `mutate.set_tags(item_id, ["lares-unclassified"])`; persist `state='classified'`; remove from `retry_queue` if present.
- **Error (timeout, network, parse failure, model returned schema-invalid output):** leave `lares-pending` in place; insert/update `retry_queue` with `due_at = now + backoff(attempts)`; increment `attempts`; persist `last_error=<reason>`.

### Retry / backoff

- Schedule: 10s → 30s → 60s → 5min cap.
- Per-item attempt counter in `items.attempts`.
- Cap at `[kmail].max_retries` (default 10). After cap, replace `lares-pending` with `lares-error`; persist `state='error'`. Subsequent `item_added` for that item still hits the skip branch (any `lares-*` tag counts).
- `drain_retry_queue` wakes on (a) `state.retry_added` `asyncio.Event` set by `consume_new_mail` after a failure, (b) the soonest `due_at` timer.

### Concurrency

**Serial classification** — single in-flight Ollama call. Local model on same host; parallelism just thrashes the GPU. Mail rate is low. If profiling later shows a bottleneck, a fixed-size `asyncio.Semaphore` is a trivial drop-in.

### Startup catchup

On every service start, before the main loop, scan inbox-like collections via `mutate` for items whose `item_id > MAX(items.item_id)` in sqlite and don't yet have a `lares-*` tag. Process them through the state machine. Bounded by a per-startup limit (config: `catchup_limit`, default 200) to avoid surprising the user with a large LLM marathon after long downtime. The manual `lares kmail catchup` / `lares kmail backfill` CLIs cover the long tail.

## 7. Configuration

`~/.config/lares/config.toml`. Validated at startup with pydantic v2 (boundary validation, not internal data plumbing). Missing required keys → hard fail with file path and bad field. Unknown keys → warning, ignored.

```toml
[lares]
log_level = "INFO"

[lares.ollama]
endpoint    = "http://127.0.0.1:11434"
model       = "qwen3:4b-instruct-2507-q4_K_M"
# Upgrade if VRAM ≥ 12 GB:  "llama3.1:8b-instruct-q4_K_M" (~6 GB, more conservative)
# Downgrade for CPU only:    "qwen3:1.7b-instruct-2507-q4_K_M" (~1 GB, slower)
# AVOID: any *-thinking-*, any deepseek-r1:* — they break JSON output.
timeout_s   = 30
temperature = 0.0

[kmail]
enabled              = true
state_db_path        = "~/.local/state/lares/kmail.db"
body_truncate_bytes  = 8192
classify_timeout_s   = 30
max_retries          = 10
catchup_limit        = 200
min_confidence       = 0.5
helper_binary_path   = ""   # dev override; "" = use importlib.resources

[kmail.tags]
personal     = "Mail from a real human writing to me directly (friends, family, individual professional correspondence)."
business     = "Inquiries, contracts, invoices, professional requests requiring a response."
newsletter   = "Marketing emails, digests, promotions, mailing list announcements."
notification = "Transactional or automated mail (GitHub notifications, calendar invites, receipts, service alerts)."

[kmail.watch]
extra_collection_names = []
```

Tag taxonomy is **fully config-driven** — changing `[kmail.tags]` regenerates the prompt and the JSON Schema. No code change.

## 8. State storage

`~/.local/state/lares/kmail.db`. Two tables; migrations applied at startup.

```sql
CREATE TABLE IF NOT EXISTS items (
    item_id      INTEGER PRIMARY KEY,           -- Akonadi item id
    state        TEXT NOT NULL,                 -- 'pending' | 'classified' | 'error'
    verdict      TEXT,                          -- tag name applied (NULL until classified)
    last_attempt TIMESTAMP NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT
);

CREATE TABLE IF NOT EXISTS retry_queue (
    item_id   INTEGER PRIMARY KEY REFERENCES items(item_id),
    due_at    TIMESTAMP NOT NULL,
    reason    TEXT NOT NULL                     -- 'ollama_down' | 'parse_fail' | 'timeout' | …
);

CREATE INDEX IF NOT EXISTS idx_retry_due ON retry_queue(due_at);
```

Sqlite is for the retry queue + observability + the startup-catchup cursor (`MAX(items.item_id)`). Idempotency itself derives from tag presence in Akonadi, not from sqlite — so a lost sqlite file does not cause re-classification of already-tagged items.

## 9. Classifier

### Model

Default `qwen3:4b-instruct-2507-q4_K_M`:

- IFEval 83.4 — beats Llama 3.1 8B (80.4) at half the resident VRAM. Instruction-following governs reliable JSON.
- ~4 GB VRAM at Q4_K_M — fits an 8 GB card alongside a desktop session.
- Native multilingual including German. (Gemma 2/3 small variants are English-only-trained — avoid.)
- Non-thinking `instruct-2507` variant — no `<think>` preamble before structured output.

Upgrade path documented in config comments: `llama3.1:8b-instruct-q4_K_M` for ≥ 12 GB VRAM. Downgrade: `qwen3:1.7b-instruct-2507-q4_K_M` for CPU-only.

Avoid-list: any `*-thinking-*` variant; any `deepseek-r1:*`; `mistral:7b-instruct` v0.3 and earlier (weaker German); `gemma2/gemma3` small (English-only training).

### API call

`POST http://127.0.0.1:11434/api/generate`:

```json
{
  "model": "<config.lares.ollama.model>",
  "prompt": "<assembled prompt>",
  "format": { "type": "object", "properties": {
      "category":   { "type": "string", "enum": ["personal","business","newsletter","notification"] },
      "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
    }, "required": ["category","confidence"], "additionalProperties": false
  },
  "options": { "temperature": 0.0 },
  "stream": false
}
```

Schema-constrained decoding (Ollama's structured-output feature) makes parse failures rare at the decoder level. Pydantic v2 model with `Literal[*config_tag_names]` for the `category` field is the second-line validation; mismatch counts as a parse failure → retry queue.

### Prompt template

Built at startup from `[kmail.tags]`:

```
You classify incoming email into exactly one of these categories:

- personal: <description from config>
- business: <description from config>
- newsletter: <description from config>
- notification: <description from config>

Respond with JSON only, no prose:
{"category": "<one of the above>", "confidence": <0.0 to 1.0>}

Email:
From: <From header>
To: <To header>
Subject: <Subject header>
List-Id: <List-Id header or empty>
Date: <Date header>

<body, truncated to body_truncate_bytes>
```

## 10. CLI surface

| Command | Purpose |
|---|---|
| `lares kmail run` | Foreground service entry point. systemd invokes this. |
| `lares kmail backfill [--limit N] [--collection NAME] [--dry-run]` | Opt-in batch pass over existing untagged inbox items. `--limit` default 100. `--dry-run` prints verdicts without applying tags. |
| `lares kmail catchup [--since ITEM_ID]` | Scan inbox(es) for items whose `item_id` exceeds the last seen sqlite row and classify any without a `lares-*` tag. Also runs automatically on service startup, bounded by `catchup_limit`. |
| `lares kmail retag <item-id> [--remove]` | Force re-classification or strip all `lares-*` tags from one item. |
| `lares kmail status [--json]` | Service state, queue depth, recent failures, last classified item. |
| `lares kmail config-check` | Validates `config.toml`, checks Ollama reachability, verifies configured model is pulled, checks Akonadi up. Exits non-zero on any failure. |
| `lares install systemd [--enable] [--start]` | Writes `lares-kmail.service` to `~/.config/systemd/user/`, runs `daemon-reload`. With `--enable`/`--start`, enables and starts. Idempotent. |
| `lares install systemd --uninstall` | Stops, disables, removes the unit, daemon-reloads. |
| `lares install config [--force]` | Writes commented default `~/.config/lares/config.toml` skeleton if missing. `--force` overwrites after `y/N` confirmation. |
| `lares install --check` | Composite pre-flight: package files present, helpers found, Akonadi up, Ollama up, model pulled, config exists & valid, unit installed. Pass/fail table. |
| `lares kmail purge --confirm` | Removes sqlite state and uninstalls service. Does not strip tags from existing Akonadi items. |

All argparse-based. No third-party CLI framework.

## 11. systemd unit & install lifecycle

`packaging/systemd/lares-kmail.service` (source of truth, copied into `src/lares/_systemd/` at build time):

```ini
[Unit]
Description=Lares — KMail/Akonadi mail triage agent
After=akonadi.service
PartOf=plasma-workspace.target

[Service]
Type=exec
ExecStart=%h/.local/bin/lares kmail run
Restart=on-failure
RestartSec=5
TimeoutStopSec=10
ProtectSystem=strict
ReadWritePaths=%h/.local/state/lares
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

End-user install path (v0.1; **no dotfiles dependency**):

```bash
uv tool install lares                          # Python pkg + builds & ships C++ helpers
lares install --check                          # pass/fail table; lists any missing deps
lares install config                           # writes config skeleton if missing
lares install systemd --enable --start         # writes unit, enables, starts
lares kmail status                             # confirms running
```

Dotfiles repo's legitimate scope remains: installing Ollama itself, the first-time `ollama pull` of the default model, and system package prerequisites (`base-devel`, `extra-cmake-modules`, KDE Frameworks 6). Per-agent install is per-agent install.

### Tag definitions

Auto-created just-in-time by `mutate` via `TagCreateJob` when a tag name isn't already defined in Akonadi. No separate install step. Lifetime: tags persist in Akonadi across reinstalls. `purge --confirm` does not strip tags from items.

### Model preflight

`config-check` and `install --check` verify the configured Ollama model is pulled. On miss:

```
✗ Ollama model "qwen3:4b-instruct-2507-q4_K_M" not pulled.
  Fix:  ollama pull qwen3:4b-instruct-2507-q4_K_M
```

No auto-pull (that is `ollama`'s job, and pulls are large enough to warrant explicit user opt-in).

## 12. Testing strategy

### Unit tests — default CI

`pytest -m "not integration"`. 1:1 file mirroring under `tests/kmail/`.

| Test file | Covers | Isolation |
|---|---|---|
| `test_config.py` | TOML load, pydantic validation, defaults, error messages on bad config. | `tomllib.loads`; no fs fixtures. |
| `test_state.py` | sqlite migrations, queue enqueue/dequeue, backoff calc, item-state transitions, attempt cap. | In-memory sqlite; injectable clock. |
| `test_classifier.py` | Prompt assembly, JSON Schema generation, parse + validate of model output (good & malformed), confidence threshold. | `pytest-httpx` mocks `httpx.AsyncClient`. |
| `test_notify.py` | NDJSON parse, reconnect-on-EOF, event dispatch shape, malformed-line handling. | Fake subprocess (Python script emitting canned NDJSON). |
| `test_mutate.py` | Request/response framing, request_id round-trip, error-code mapping, restart-on-crash. | Same fake-subprocess pattern. |
| `test_service.py` | Per-message state machine: skip-when-tagged, pending → verdict path, pending → error path, retry-drain order. | All four collaborators injected as fakes; `pytest-asyncio strict`. |
| `test_cli.py` | argparse parsing, subcommand dispatch, `install systemd` writes correct file content, exit codes. | `tmp_path` for fs ops. |
| `test_tags.py` | Namespace constants, `is_lares_tag()` predicate, replacement semantics. | Pure unit. |

All async tests under `@pytest.mark.asyncio`. Parametrized table cases — no in-test `for` loops generating cases.

### Synthetic fixtures

Four `.eml` files, mix of German and English, faked synthetic-domain sender addresses. No real mail, ever (CLAUDE.md hard rule).

### Integration tests — manual/scheduled CI job

`pytest -m integration`. Opt-in.

- **`test_helpers_integration.py`** — spawns real C++ helpers against a sandboxed Akonadi (separate `XDG_DATA_HOME`, `akonadictl start`). Creates synthetic items via a tiny C++ fixture binary, asserts `notify` emits the event and `mutate fetch`/`set_tags` round-trip correctly.
- **`test_ollama_integration.py`** — requires `OLLAMA_TEST_MODEL` env var. Runs the four `.eml` fixtures through the real classifier, asserts verdict matches expected category and confidence ≥ 0.5.

### CI shape

- Default job (every push/PR): build deps + `uv sync` + `ruff check` + `ruff format --check` + `pyright` + `pytest -m "not integration"`.
- Integration job (`workflow_dispatch` + nightly): adds `akonadi` runtime + a model-baked image, runs `pytest -m integration`.

### Out of test scope

- C++ helpers' internals as code-under-test (tested at protocol boundary via integration suite).
- Real-model classification accuracy beyond the canonical four-fixture sanity check.

## 13. Known risks

1. **Akonadi C++ API drift.** Helpers depend on Akonadi 26.x. KDE PIM is stable but not frozen. Mitigation: pin minimum KF6 version in CMake; release-checklist item per KDE 6.X bump.
2. **`format` schema enforcement varies by Ollama model.** `qwen3:4b-instruct-2507` is well-behaved; user-selected wrong-class models can break JSON parsing. Mitigation: document in README; future `config-check` warning for known-bad model classes.
3. **Body truncation may chop signal-rich content.** First 8 KB is decisive for newsletters/notifications; risky for long personal mail. Acceptable risk; configurable per `[kmail].body_truncate_bytes`.
4. **`Akonadi::Monitor` may miss events under server restart in narrow windows.** Mitigation: startup catchup scan + manual `lares kmail catchup`.
5. **Tag definitions are global per Akonadi instance.** Synced-Akonadi setups across machines re-classify on the second machine (tag state is per-item). Edge case; documented limitation.

## 14. Documentation deliverables (part of v0.1)

- `README.md` updated: install steps, deps, `lares install …` flow, model selection guidance, troubleshooting (Ollama down, Akonadi headless, model not pulled).
- This spec, committed to `docs/superpowers/specs/`.
- `CLAUDE.md` updated: note `src/akonadi_bridge/` exists and build backend is `scikit-build-core`.

## 15. Decisions journal

| Decision | Choice | Rationale |
|---|---|---|
| Action shape | Tag only (no folder moves) | Reversible; KMail filters can compose moves from tags. |
| Default taxonomy | personal / business / newsletter / notification | Matches user workflow; matches convergent industry pattern (Gmail tabs, Hey.com). |
| Trigger | Akonadi D-Bus signal (via C++ Monitor helper) | Lowest latency; no polling. |
| Mutation path | Two C++ Qt6 helpers shipped in wheel | Only viable headless path in 2026; ~300 LoC total. |
| Error handling | `lares-pending` tag + sqlite retry queue | Visible in KMail; recoverable; explicit. |
| Idempotency | Tag-based skip; opt-in CLI backfill; bounded startup catchup | Avoids LLM marathon on first install; survives lost sqlite. |
| Watch scope | Auto-detected inbox-like collections | Multi-account zero-config; misses custom landing folders (acceptable). |
| Build backend | `scikit-build-core` | Standard PEP 517 backend for Python + native code. |
| Helpers location | `src/akonadi_bridge/` → installed to `lares/_bin/` | Inside-wheel; `importlib.resources` discovery; no `$PATH` pollution. |
| Default model | `qwen3:4b-instruct-2507-q4_K_M` | IFEval 83.4, ~4 GB VRAM, native multilingual incl. German, non-thinking variant. |
| Structured output | Ollama `format` JSON Schema + `temperature: 0` | Decoder-level shape guarantee; deterministic. |
| Confidence threshold | 0.5; below → `lares-unclassified` (configurable) | Conservative; lets the user see the agent hedged. |
| Concurrency | Serial classification (single in-flight) | Local model; parallelism thrashes GPU. |
| Backoff | 10s → 30s → 60s → 5min, 10 attempts → `lares-error` | Quick recovery on transient outage; bounded on persistent. |
| Install ownership | Agent owns full install lifecycle (systemd unit, config, preflight) | No shortcuts to dotfiles; per-app artifacts belong with the app. |
| `lares.core` extraction | Deferred until KRunner exists | "Two implementations before abstraction" — CLAUDE.md root §2. |
