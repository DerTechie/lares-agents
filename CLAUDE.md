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
- Both agents run as `systemd --user` services — the KMail triage agent watches Akonadi over D-Bus, the KRunner agent owns a D-Bus service name implementing `org.kde.krunner1`.
- Single user config at `~/.config/lares/config.toml`, with per-agent `[<agent>]` sections.
- Degrade gracefully when Ollama is unreachable or the configured model is missing.
- License headers / SPDX tags on every source file.

---

## Code quality

The bar is **production-grade Python written by someone who has shipped Python 3.12+ code in the last year.** No 2015-era patterns. No defensive code for situations that cannot happen. No docstrings that just restate the signature. If you find yourself writing boilerplate, stop and check whether the stdlib already has it.

### Type checking — mandatory

- Strict typing across the codebase. The chosen type checker is **`pyright --strict`** (fastest, best structural-typing inference). `mypy --strict` is an acceptable swap if preferred — same strictness floor, update this line if you switch.
- Modern syntax: PEP 604 unions (`int | str`), PEP 695 generics (`def f[T](x: T) -> T`), `type Alias = ...` statements, `Self` from `typing`.
- Public functions: typed parameters **and** typed return. Private helpers may rely on return-type inference.
- `Protocol` for structural typing. Bare `Any` is a smell and needs an inline justification (`# Any: third-party D-Bus payload, shape varies`).
- Run the type checker in CI; type errors are build failures.

### Linting and formatting

- `ruff check` and `ruff format` are the only tools. No black, no isort, no flake8 — `ruff` already covers them.
- Warnings are errors in CI. No `# noqa` without an inline rationale (`# noqa: E501 — generated SQL, wrapping would obscure intent`).
- The active rule set lives in `pyproject.toml`. Widen it as patterns stabilise; narrow it only with a documented reason in the same PR.

### Idioms

- Lean on Python 3.12+ where it clarifies: `match` for tagged dispatch, the walrus where it shortens read-then-act, PEP 695 generics, structural pattern matching.
- `pathlib.Path` over `os.path`. `subprocess.run(..., check=True, capture_output=True)` — never `os.system` or shell strings.
- `dataclasses.dataclass(slots=True, frozen=True)` for internal value objects. **Pydantic v2** at boundaries only — config parsing, D-Bus payload validation, Ollama response schemas — not for internal data.
- `tomllib` (stdlib) for TOML reads, not `tomli` or `toml`.
- f-strings for formatting. No `%`-formatting, no `.format()`.
- Iterators and comprehensions over hand-rolled loops *when they read more clearly*. Comprehensions that don't fit on one screen are a worse choice than the loop.

### Error handling

- Trust internal code and framework guarantees. Validate only at system boundaries: config file load, D-Bus calls, Ollama HTTP, IMAP-side data shape.
- Specific exception types. Custom exceptions centralised in `lares.core.errors` (once that module exists).
- No bare `except:`, no `except Exception: pass`. Use `contextlib.suppress(SpecificError)` for intentional ignoring, with a one-line comment on *why*.
- Don't catch-and-rewrap to "add context" without adding actual context — the traceback already has the call site.
- Graceful degradation (missing Ollama, missing model) is required (root §5 of the overlord), but degrade *explicitly* with a logged reason — never silently.

### Logging

- Stdlib `logging`, module-level loggers: `logger = logging.getLogger(__name__)`.
- No `print()` in shipped code.
- Pass log arguments, do not pre-format: `logger.info("triaged %d items", n)` — not `logger.info(f"triaged {n} items")`. Lazy formatting matters when the level is filtered out.
- **Never log mail bodies, prompt contents, model completions, or any user-data payload above DEBUG, and at DEBUG only behind an explicit opt-in flag.** Local-first does not absolve us of hygiene; `journalctl` output can be world-readable in some configurations.

### Async vs sync

- Both KMail (Akonadi over D-Bus) and KRunner (`org.kde.krunner1` over D-Bus) are I/O-bound and intrinsically async — default to `asyncio`. Recommended libraries when need arises: `dbus-next` (async D-Bus, well-maintained), `httpx.AsyncClient` for the Ollama HTTP path (the official `ollama` Python client wraps it).
- Sync only at CLI entry points and pure-CPU helpers.
- One event loop per service, owned by the entry point. No `asyncio.run` inside an already-running loop.

### Naming and structure

- `snake_case` modules and functions; `PascalCase` classes; `UPPER_SNAKE` constants.
- One concept per module. When a file crosses ~300 lines, look for a natural split before adding more.
- Tests mirror source: `src/lares/foo/bar.py` ↔ `tests/foo/test_bar.py`.
- Test names read as sentences: `test_triage_skips_already_tagged_messages`, not `test_triage_1`.

### Testing

- `pytest` only — never `unittest.TestCase`.
- Synthetic fixtures only. Real mail, real IMAP credentials, and real Akonadi state never appear in fixtures or CI (overlord hard rule).
- Integration tests marked `@pytest.mark.integration`; CI runs `pytest -m "not integration"` by default. Integration suite runs on a manual or scheduled job.
- Parameterise table cases with `pytest.mark.parametrize`. No `for` loops generating cases inside a test body.
- Async tests via `pytest-asyncio` and `@pytest.mark.asyncio`.

### Anti-patterns

- No premature abstractions. No `ABC`, no plugin registries, no "agent base class" until a *second* concrete implementation exists (root §2 of the overlord).
- No `setup.py`, no `requirements.txt`. `pyproject.toml` and `uv.lock` are the only sources of truth.
- No `from x import *`. Explicit imports, ordered by `ruff`.
- No global mutable state. Pass config and clients explicitly — the DI graph is shallow enough to do by hand.
- No catching `KeyboardInterrupt` or `SystemExit` outside the single top-level entry point.
- No docstrings that just restate the signature. Docstrings on public-API functions and on anything whose *why* is non-obvious from the name. Otherwise, none.
- No comments that narrate `what` the code does — well-named identifiers do that. Comments answer `why` for non-obvious decisions.

### Where these rules are enforced

- **`pyproject.toml`** — ruff rule selection, per-file ignores, and `[tool.pyright]` strict-mode config.
- **`.github/workflows/ci.yml`** — runs `ruff check`, `ruff format --check`, `pyright`, and `pytest -m "not integration"` on every push to `main` and every PR. Failures block the merge.
- **`.pre-commit-config.yaml`** — same checks at commit time, plus whitespace / EOF / TOML / YAML hygiene. Run `pre-commit install` once after cloning to enable.

---

## What does *not* belong here

- Strategy, brand, GTM, monetization, prior-art landscape, build-in-public artifacts — those live in the private overlord.
- Workstation bootstrap (Ollama install, default model pulls, system packages) — that lives in [`DerTechie/dotfiles`](https://github.com/DerTechie/dotfiles).
- Infrastructure (Terraform, hosting) and the marketing site — separate repos, planned but not yet introduced.
