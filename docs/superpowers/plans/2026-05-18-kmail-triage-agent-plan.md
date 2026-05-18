# `lares.kmail` v0.1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v0.1 `lares.kmail` Akonadi mail-triage agent as specified in `docs/superpowers/specs/2026-05-18-kmail-triage-agent-design.md`. The agent watches inbox-like Akonadi collections, classifies new mail via local Ollama, and applies one of four Akonadi tags. Includes two C++/Qt6 helpers shipped in the wheel, a Python asyncio service, a complete CLI for run / status / install / backfill, and a self-contained install lifecycle (no shortcuts to dotfiles).

**Architecture:** Two small C++/Qt6 helper binaries (`lares-akonadi-notify`, `lares-akonadi-mutate`) own the Akonadi C++ API surface and expose JSON/NDJSON line protocols on stdio. A Python asyncio service supervises them as subprocesses, owns all policy (taxonomy, retry, backoff, persistence), classifies via Ollama's structured-output endpoint, and applies Akonadi tags via the mutate helper. Build via `scikit-build-core` so `uv tool install lares` builds and ships both languages atomically.

**Tech Stack:** Python 3.12 (asyncio, sqlite3, tomllib, argparse, importlib.resources), httpx (Ollama HTTP), pydantic v2 (config validation, response parsing), Qt6 + KPim6::AkonadiCore + KPim6::Mime (C++ helpers), CMake + scikit-build-core (build), ruff + pyright + pytest + pytest-asyncio + pytest-httpx + freezegun (dev tools).

**Conventions:**
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).
- Every public function gets a type annotation. PEP 604 unions, PEP 695 generics. `pyright --strict` is the floor.
- `pytest-asyncio` mode is `strict`; every async test gets `@pytest.mark.asyncio`.
- No `print()` in shipped code (T20). Module-level `logger = logging.getLogger(__name__)`.
- f-strings, `pathlib.Path`, `subprocess.run(..., check=True, capture_output=True)`.
- SPDX header `# SPDX-License-Identifier: MIT` on every new source file.

**Quality gates (must pass before each commit):**
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
```
If any fails, fix root cause — never `# noqa` without an inline rationale; never weaken pyright config to make it pass.

---

## File structure

```
lares-agents/
├── pyproject.toml                              # MODIFY (Task 1)
├── CMakeLists.txt                              # CREATE (Task 2)
├── .github/workflows/ci.yml                    # MODIFY (Task 3)
├── README.md                                   # MODIFY (Task 24)
├── src/lares/
│   ├── __init__.py                             # MODIFY (Task 4 — expose kmail subpackage)
│   ├── _config/
│   │   └── config.toml.skel                    # CREATE (Task 19)
│   └── kmail/
│       ├── __init__.py                         # CREATE (Task 4)
│       ├── tags.py                             # CREATE (Task 4)
│       ├── config.py                           # CREATE (Task 5)
│       ├── state.py                            # CREATE (Task 6)
│       ├── classifier.py                       # CREATE (Task 7)
│       ├── notify.py                           # CREATE (Task 8)
│       ├── mutate.py                           # CREATE (Task 9)
│       ├── service.py                          # CREATE (Task 10)
│       └── cli.py                              # CREATE (Task 14, grown by 15–22)
├── src/akonadi_bridge/
│   ├── CMakeLists.txt                          # CREATE (Task 12)
│   ├── notify.cpp                              # CREATE (Task 12)
│   └── mutate.cpp                              # CREATE (Task 13)
├── packaging/systemd/
│   └── lares-kmail.service                     # CREATE (Task 20)
└── tests/kmail/
    ├── __init__.py                             # CREATE (Task 4)
    ├── conftest.py                             # CREATE (Task 4, grown later)
    ├── test_tags.py                            # CREATE (Task 4)
    ├── test_config.py                          # CREATE (Task 5)
    ├── test_state.py                           # CREATE (Task 6)
    ├── test_classifier.py                      # CREATE (Task 7)
    ├── test_notify.py                          # CREATE (Task 8)
    ├── test_mutate.py                          # CREATE (Task 9)
    ├── test_service.py                         # CREATE (Task 10)
    ├── test_cli.py                             # CREATE (Task 14, grown by 15–22)
    └── fixtures/
        ├── personal.eml                        # CREATE (Task 11)
        ├── business.eml                        # CREATE (Task 11)
        ├── newsletter.eml                      # CREATE (Task 11)
        └── notification.eml                    # CREATE (Task 11)
```

Existing files (`src/lares/__init__.py`, `tests/test_smoke.py`) stay.

---

## Task 1 — Migrate build backend to `scikit-build-core`; add runtime + dev deps

**Files:**
- Modify: `pyproject.toml`

**Why:** Spec §4 mandates `scikit-build-core` so a single `uv tool install lares` builds both Python and C++. Also need runtime deps (`httpx`, `pydantic`) and dev deps (`pytest-httpx`, `freezegun`).

- [ ] **Step 1: Edit `pyproject.toml`**

Replace the existing `[build-system]` block and the `[tool.hatch.build.targets.wheel]` block; add runtime deps; add new dev deps; add `[tool.scikit-build]` config.

```toml
[project]
name = "lares"
version = "0.0.0"
description = "Local-first AI agents for the Linux desktop, built on Ollama."
readme = "README.md"
requires-python = ">=3.12"
license = "MIT"
license-files = ["LICENSE"]
authors = [{ name = "Mike Esser", email = "info@dertechie.de" }]
keywords = ["kde", "plasma", "kmail", "krunner", "ollama", "local-ai", "linux-desktop"]
classifiers = [
    "Development Status :: 1 - Planning",
    "Environment :: X11 Applications :: KDE",
    "Intended Audience :: End Users/Desktop",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3 :: Only",
]
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.7",
]

[project.scripts]
lares = "lares.kmail.cli:main"

[project.urls]
Homepage = "https://github.com/DerTechie/lares-agents"
Issues = "https://github.com/DerTechie/lares-agents/issues"

[build-system]
requires = ["scikit-build-core>=0.10"]
build-backend = "scikit_build_core.build"

[tool.scikit-build]
minimum-version = "0.10"
cmake.version = ">=3.20"
ninja.make-fallback = true
wheel.packages = ["src/lares"]
build-dir = "build/{wheel_tag}"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.32",
    "freezegun>=1.5",
    "ruff>=0.7",
    "pyright>=1.1.385",
]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src"]

[tool.ruff.lint]
select = [
    "E", "W", "F", "I", "UP", "B", "SIM", "C4", "PIE", "RET",
    "T20", "PT", "TCH", "ANN", "N", "RUF", "PL",
]
ignore = [
    "PLR0913",  # too many arguments — judgement call, not a rule
]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["ANN", "PLR2004"]

[tool.ruff.lint.flake8-type-checking]
runtime-evaluated-base-classes = ["pydantic.BaseModel"]

[tool.pyright]
include = ["src", "tests"]
pythonVersion = "3.12"
pythonPlatform = "Linux"
typeCheckingMode = "strict"
reportMissingTypeStubs = "warning"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
asyncio_mode = "strict"
markers = [
    "integration: integration tests that require a live Akonadi or Ollama instance (deselect with '-m \"not integration\"')",
]
```

- [ ] **Step 2: Verify the existing smoke test still runs**

Run: `uv sync && uv run pytest -m "not integration"`

Expected: `tests/test_smoke.py::test_lares_package_imports` passes. (scikit-build-core will warn "no CMakeLists.txt found at the root" — that's Task 2's job; for now it falls back to a Python-only wheel build. If `uv sync` fails because CMakeLists is required, proceed to Task 2 first and merge Task 1 and Task 2 as one commit.)

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: migrate to scikit-build-core and declare runtime + dev deps

Switches the PEP 517 backend so the upcoming C++ helpers can be built
as part of \`uv tool install lares\`. Adds httpx and pydantic to runtime
deps and pytest-httpx + freezegun to dev deps for the kmail agent."
```

---

## Task 2 — Add root `CMakeLists.txt` (no targets yet)

**Files:**
- Create: `CMakeLists.txt`

**Why:** `scikit-build-core` requires a CMakeLists at the repo root. We keep it minimal: declares the project, optionally pulls in `src/akonadi_bridge/` once that subdirectory has its own CMakeLists (Tasks 12/13). For Tasks 1–11 there's nothing to compile, so the helper subdir block is gated behind a file check.

- [ ] **Step 1: Create `CMakeLists.txt`**

```cmake
# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.20)
project(lares LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# The Akonadi-bridge C++ helpers (lares-akonadi-notify, lares-akonadi-mutate)
# are added once their CMakeLists.txt is in place. Gating keeps the
# Python-only wheel buildable during early bootstrap tasks.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/akonadi_bridge/CMakeLists.txt")
    add_subdirectory(src/akonadi_bridge)
endif()
```

- [ ] **Step 2: Verify the wheel still builds**

Run: `uv sync`

Expected: completes without error; no C++ compiled (CMake reports "project: lares" and exits without targets).

- [ ] **Step 3: Verify smoke test still passes**

Run: `uv run pytest -m "not integration"`

Expected: `tests/test_smoke.py` passes.

- [ ] **Step 4: Commit**

```bash
git add CMakeLists.txt
git commit -m "build: add root CMakeLists.txt for scikit-build-core

Minimal config — declares the project and conditionally pulls in the
akonadi-bridge subdir once its CMakeLists exists. Keeps the wheel
buildable while we lay groundwork for the C++ helpers."
```

---

## Task 3 — Update CI to install Qt6 / KPim6 / cmake / ninja

**Files:**
- Modify: `.github/workflows/ci.yml`

**Why:** Spec §4 requires CI to build the C++ helpers on every PR so compile breakage surfaces early. KDE 6 PIM (`KPim6Akonadi`, `KPim6Mime`) is **not packaged on Ubuntu Noble 24.04 (`ubuntu-latest`'s current image)** — only KDE 5 is. The first Ubuntu suite that ships them is 25.10 (Questing), where they live in the unprefixed Debian packages `libakonadi-dev` and `libkmime-dev` (both ship `KPim6*Config.cmake` files). The CI job therefore runs inside an `ubuntu:25.10` container hosted by a `ubuntu-latest` runner. Even before Task 12 lands real C++, having the deps installed is a no-op cost and avoids a later "CI broke" commit.

- [ ] **Step 1: Edit `.github/workflows/ci.yml`**

The job switches to a container-based job. The container starts as root (no `sudo`), so we install the base bootstrap tooling (`git`, `curl`, `ca-certificates`) before `actions/checkout@v4` runs, then the KDE 6 deps. The full file becomes:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    container: ubuntu:25.10
    timeout-minutes: 15
    steps:
      - name: Install base tooling
        run: |
          apt-get update
          apt-get install -y --no-install-recommends \
            ca-certificates curl git

      - uses: actions/checkout@v4

      - name: Install Qt6 / KPim6 / build tools
        run: |
          apt-get install -y --no-install-recommends \
            build-essential cmake ninja-build extra-cmake-modules \
            qt6-base-dev libakonadi-dev libkmime-dev

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python 3.12
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --frozen

      - name: ruff check
        run: uv run ruff check .

      - name: ruff format --check
        run: uv run ruff format --check .

      - name: pyright (strict)
        run: uv run pyright

      - name: pytest (unit only)
        run: uv run pytest -m "not integration"
```

- [ ] **Step 2: Commit (no local verification — workflow runs on push)**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: install Qt6/KF6 build deps so the C++ helpers can compile"
```

---

## Task 4 — `lares.kmail.tags` (namespace constants + predicate)

**Files:**
- Create: `src/lares/kmail/__init__.py`
- Create: `src/lares/kmail/tags.py`
- Create: `tests/kmail/__init__.py`
- Create: `tests/kmail/conftest.py`
- Create: `tests/kmail/test_tags.py`

**Why:** Spec §6 lists `tags.py` as the namespace constants + `is_lares_tag()` predicate. Smallest module, builds the foundation other modules use.

- [ ] **Step 1: Create the empty package init files**

`src/lares/kmail/__init__.py`:
```python
# SPDX-License-Identifier: MIT
```

`tests/kmail/__init__.py`:
```python
# SPDX-License-Identifier: MIT
```

`tests/kmail/conftest.py`:
```python
# SPDX-License-Identifier: MIT
```

- [ ] **Step 2: Write the failing test**

`tests/kmail/test_tags.py`:
```python
# SPDX-License-Identifier: MIT
import pytest

from lares.kmail.tags import (
    LARES_ERROR,
    LARES_PENDING,
    LARES_TAG_PREFIX,
    LARES_UNCLASSIFIED,
    is_lares_tag,
)


def test_namespace_prefix_is_consistent():
    assert LARES_PENDING.startswith(LARES_TAG_PREFIX)
    assert LARES_UNCLASSIFIED.startswith(LARES_TAG_PREFIX)
    assert LARES_ERROR.startswith(LARES_TAG_PREFIX)


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("lares-pending", True),
        ("lares-unclassified", True),
        ("lares-error", True),
        ("lares-personal", True),
        ("personal", False),
        ("Personal", False),
        ("", False),
        ("LARES-PENDING", False),  # case-sensitive
        ("lares_pending", False),  # underscore, not dash
    ],
)
def test_is_lares_tag(tag: str, expected: bool) -> None:
    assert is_lares_tag(tag) is expected
```

- [ ] **Step 3: Run the test; verify failure**

Run: `uv run pytest tests/kmail/test_tags.py -v`

Expected: `ImportError: cannot import name 'LARES_PENDING' from 'lares.kmail.tags'` (or `ModuleNotFoundError`).

- [ ] **Step 4: Implement**

`src/lares/kmail/tags.py`:
```python
# SPDX-License-Identifier: MIT
"""Tag namespace constants and predicate.

All Lares-managed Akonadi tags share the `lares-` prefix. The control tags
(`lares-pending`, `lares-unclassified`, `lares-error`) are reserved; user
taxonomy tags from `[kmail.tags]` are prefixed with `lares-` when applied
to items so the mutate helper's namespace-scoped replace semantics work
uniformly.
"""

LARES_TAG_PREFIX = "lares-"

LARES_PENDING = "lares-pending"
LARES_UNCLASSIFIED = "lares-unclassified"
LARES_ERROR = "lares-error"


def is_lares_tag(tag: str) -> bool:
    return tag.startswith(LARES_TAG_PREFIX)
```

- [ ] **Step 5: Run the test; verify pass**

Run: `uv run pytest tests/kmail/test_tags.py -v`

Expected: 10 passed (1 prefix check + 9 parametrized predicate cases).

- [ ] **Step 6: Run all quality gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add src/lares/kmail/ tests/kmail/
git commit -m "feat(kmail): add tags namespace constants and predicate"
```

---

## Task 5 — `lares.kmail.config` (pydantic v2 + tomllib loader)

**Files:**
- Create: `src/lares/kmail/config.py`
- Create: `tests/kmail/test_config.py`

**Why:** Spec §7. Pydantic v2 boundary validation; configurable taxonomy drives the prompt; explicit hard-fail with the file path and bad field on validation error.

**Note on user taxonomy tag names:** Spec §6 mutate contract says tags get auto-created via `TagCreateJob`. To keep tag namespacing consistent across the codebase, the `Classifier` and `service` always apply user-taxonomy tags **with the `lares-` prefix attached** (e.g. `lares-personal`, not `personal`). The config keys (`personal`, `business`, ...) are bare; the prefix is added at point-of-use. `tags.py` predicate then correctly identifies them as Lares-managed.

- [ ] **Step 1: Write the failing test**

`tests/kmail/test_config.py`:
```python
# SPDX-License-Identifier: MIT
from pathlib import Path

import pytest
from pydantic import ValidationError

from lares.kmail.config import LaresConfig, load_config


_FULL = """
[lares]
log_level = "DEBUG"

[lares.ollama]
endpoint    = "http://127.0.0.1:11434"
model       = "qwen3:4b-instruct-2507-q4_K_M"
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
helper_binary_path   = ""

[kmail.tags]
personal     = "A human writing to me."
business     = "Business inquiry."
newsletter   = "Marketing or digest."
notification = "Transactional notice."

[kmail.watch]
extra_collection_names = []
"""


def test_load_valid_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(_FULL)
    cfg = load_config(cfg_file)
    assert isinstance(cfg, LaresConfig)
    assert cfg.lares.ollama.model == "qwen3:4b-instruct-2507-q4_K_M"
    assert cfg.kmail.min_confidence == 0.5
    assert set(cfg.kmail.tags) == {"personal", "business", "newsletter", "notification"}


def test_defaults_apply_when_kmail_section_minimal(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "qwen3:4b-instruct-2507-q4_K_M"

[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    cfg = load_config(cfg_file)
    assert cfg.kmail.body_truncate_bytes == 8192
    assert cfg.kmail.max_retries == 10
    assert cfg.lares.ollama.endpoint == "http://127.0.0.1:11434"


def test_state_db_path_user_home_expanded(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "x"

[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    cfg = load_config(cfg_file)
    assert not str(cfg.kmail.state_db_path).startswith("~")
    assert cfg.kmail.state_db_path.is_absolute()


def test_min_confidence_must_be_in_range(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "x"

[kmail]
min_confidence = 1.5

[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    with pytest.raises(ValidationError):
        load_config(cfg_file)


def test_tags_must_be_non_empty(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[lares.ollama]
model = "x"

[kmail.tags]
"""
    )
    with pytest.raises(ValidationError):
        load_config(cfg_file)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_model_must_be_set(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[kmail.tags]
personal = "h"
business = "b"
newsletter = "n"
notification = "t"
"""
    )
    with pytest.raises(ValidationError):
        load_config(cfg_file)
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_config.py -v`

Expected: `ModuleNotFoundError: No module named 'lares.kmail.config'`.

- [ ] **Step 3: Implement**

`src/lares/kmail/config.py`:
```python
# SPDX-License-Identifier: MIT
"""Configuration loader for Lares agents.

Single source of truth: `~/.config/lares/config.toml`. Validated at startup
with pydantic v2; missing required keys hard-fail with the file path
embedded in the error message.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OllamaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: str = "http://127.0.0.1:11434"
    model: str
    timeout_s: Annotated[int, Field(ge=1, le=600)] = 30
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0


class LaresShared(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    log_level: str = "INFO"
    ollama: OllamaConfig

    @field_validator("log_level")
    @classmethod
    def _log_level_known(cls, v: str) -> str:
        if v.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unknown log_level: {v!r}")
        return v.upper()


class KMailWatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    extra_collection_names: list[str] = Field(default_factory=list)


class KMailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    state_db_path: Path = Path("~/.local/state/lares/kmail.db")
    body_truncate_bytes: Annotated[int, Field(ge=128, le=1_048_576)] = 8192
    classify_timeout_s: Annotated[int, Field(ge=1, le=600)] = 30
    max_retries: Annotated[int, Field(ge=0, le=1000)] = 10
    catchup_limit: Annotated[int, Field(ge=0, le=100_000)] = 200
    min_confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    helper_binary_path: str = ""
    tags: dict[str, str]
    watch: KMailWatch = Field(default_factory=KMailWatch)

    @field_validator("tags")
    @classmethod
    def _at_least_one_tag(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("kmail.tags must define at least one tag")
        for name, desc in v.items():
            if not name or not desc:
                raise ValueError(f"kmail.tags entry must be non-empty: {name!r}={desc!r}")
        return v

    @field_validator("state_db_path", mode="after")
    @classmethod
    def _expand_user(cls, v: Path) -> Path:
        return v.expanduser().resolve()


class LaresConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lares: LaresShared
    kmail: KMailConfig


def load_config(path: Path) -> LaresConfig:
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    # Promote bare `[lares.ollama]` (without [lares]) into a synthesised [lares] block.
    if "lares" not in data:
        data["lares"] = {}
    if "ollama" not in data["lares"] and "lares.ollama" in data:
        # tomllib already nests dotted-table keys, this branch is paranoia only.
        data["lares"]["ollama"] = data.pop("lares.ollama")
    return LaresConfig.model_validate(data)
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_config.py -v`

Expected: 7 passed.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/config.py tests/kmail/test_config.py
git commit -m "feat(kmail): add pydantic v2 config loader with TOML boundary validation"
```

---

## Task 6 — `lares.kmail.state` (sqlite migrations + retry queue)

**Files:**
- Create: `src/lares/kmail/state.py`
- Create: `tests/kmail/test_state.py`

**Why:** Spec §8. Two tables; queue ops; per-item attempt counter; exponential backoff (10s → 30s → 60s → 5min cap). Synchronous sqlite (run in default executor via `asyncio.to_thread` from `service.py`).

- [ ] **Step 1: Write the failing test**

`tests/kmail/test_state.py`:
```python
# SPDX-License-Identifier: MIT
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time

from lares.kmail.state import ItemState, State, backoff_delay


def test_backoff_curve() -> None:
    assert backoff_delay(0) == timedelta(seconds=10)
    assert backoff_delay(1) == timedelta(seconds=30)
    assert backoff_delay(2) == timedelta(seconds=60)
    assert backoff_delay(3) == timedelta(seconds=300)
    assert backoff_delay(10) == timedelta(seconds=300)  # capped


def _open(tmp_path: Path) -> State:
    return State(tmp_path / "state.db")


def test_record_classified_creates_row() -> None:
    s = State(":memory:")
    s.record_classified(item_id=42, verdict="lares-personal")
    row = s.get(42)
    assert row is not None
    assert row.item_id == 42
    assert row.state is ItemState.CLASSIFIED
    assert row.verdict == "lares-personal"
    assert row.attempts == 0
    assert row.last_error is None


@freeze_time("2026-05-18 12:00:00")
def test_enqueue_retry_inserts_with_backoff() -> None:
    s = State(":memory:")
    s.record_pending(item_id=7)
    s.enqueue_retry(item_id=7, reason="ollama_down")
    due = s.peek_next_due()
    assert due is not None
    assert due.item_id == 7
    assert due.due_at == datetime(2026, 5, 18, 12, 0, 10, tzinfo=UTC)


@freeze_time("2026-05-18 12:00:00")
def test_enqueue_retry_uses_existing_attempts_count() -> None:
    s = State(":memory:")
    s.record_pending(item_id=7)
    s.enqueue_retry(item_id=7, reason="ollama_down")  # attempt 1 → 10s
    s.bump_attempts(7, "ollama_down")
    s.enqueue_retry(item_id=7, reason="ollama_down")  # attempt 2 → 30s
    due = s.peek_next_due()
    assert due is not None
    assert due.due_at == datetime(2026, 5, 18, 12, 0, 30, tzinfo=UTC)


@freeze_time("2026-05-18 12:00:00")
def test_pop_due_returns_only_due_items() -> None:
    s = State(":memory:")
    s.record_pending(item_id=1)
    s.record_pending(item_id=2)
    s.enqueue_retry(item_id=1, reason="x")  # due at +10s
    s.bump_attempts(2, "x")
    s.bump_attempts(2, "x")
    s.bump_attempts(2, "x")
    s.enqueue_retry(item_id=2, reason="x")  # attempt 4 → 300s

    with freeze_time("2026-05-18 12:00:15"):
        due_now = s.pop_due(limit=10)
    assert [d.item_id for d in due_now] == [1]


def test_max_item_id_returns_none_on_empty() -> None:
    s = State(":memory:")
    assert s.max_item_id() is None


def test_max_item_id_returns_max() -> None:
    s = State(":memory:")
    s.record_classified(item_id=5, verdict="lares-personal")
    s.record_classified(item_id=99, verdict="lares-business")
    s.record_pending(item_id=42)
    assert s.max_item_id() == 99


def test_remove_from_queue_idempotent() -> None:
    s = State(":memory:")
    s.record_pending(item_id=1)
    s.enqueue_retry(item_id=1, reason="x")
    s.remove_from_queue(1)
    s.remove_from_queue(1)  # double remove must not raise
    assert s.peek_next_due() is None


def test_record_error_after_cap(tmp_path: Path) -> None:
    s = _open(tmp_path)
    s.record_error(item_id=11, reason="exhausted_retries")
    row = s.get(11)
    assert row is not None
    assert row.state is ItemState.ERROR
    assert row.last_error == "exhausted_retries"
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_state.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/lares/kmail/state.py`:
```python
# SPDX-License-Identifier: MIT
"""Sqlite-backed state for the kmail triage agent.

Two tables: `items` (one row per item we've touched) and `retry_queue`
(items awaiting reclassification with exponential backoff). All write
ops are synchronous; the service runs them in the default executor via
`asyncio.to_thread`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path


_BACKOFF_SCHEDULE = [
    timedelta(seconds=10),
    timedelta(seconds=30),
    timedelta(seconds=60),
    timedelta(seconds=300),
]


def backoff_delay(attempt: int) -> timedelta:
    """Return the delay before retry attempt N (0-indexed). Caps at 5 minutes."""
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt}")
    idx = min(attempt, len(_BACKOFF_SCHEDULE) - 1)
    return _BACKOFF_SCHEDULE[idx]


class ItemState(StrEnum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class ItemRow:
    item_id: int
    state: ItemState
    verdict: str | None
    last_attempt: datetime
    attempts: int
    last_error: str | None


@dataclass(slots=True, frozen=True)
class QueueRow:
    item_id: int
    due_at: datetime
    reason: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id      INTEGER PRIMARY KEY,
    state        TEXT NOT NULL,
    verdict      TEXT,
    last_attempt TIMESTAMP NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT
);
CREATE TABLE IF NOT EXISTS retry_queue (
    item_id   INTEGER PRIMARY KEY REFERENCES items(item_id),
    due_at    TIMESTAMP NOT NULL,
    reason    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retry_due ON retry_queue(due_at);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(raw: str | datetime) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    # sqlite returns TIMESTAMP columns as ISO 8601 strings.
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class State:
    def __init__(self, db_path: Path | str) -> None:
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(
            str(db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # autocommit; we'll use BEGIN/COMMIT explicitly
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def record_pending(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO items(item_id, state, last_attempt, attempts)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(item_id) DO UPDATE
                  SET state='pending', last_attempt=excluded.last_attempt
                """,
                (item_id, ItemState.PENDING.value, _now().isoformat()),
            )

    def record_classified(self, item_id: int, verdict: str) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO items(item_id, state, verdict, last_attempt, attempts)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(item_id) DO UPDATE
                  SET state='classified',
                      verdict=excluded.verdict,
                      last_attempt=excluded.last_attempt,
                      last_error=NULL
                """,
                (item_id, ItemState.CLASSIFIED.value, verdict, _now().isoformat()),
            )
            c.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))

    def record_error(self, item_id: int, reason: str) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO items(item_id, state, last_attempt, attempts, last_error)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(item_id) DO UPDATE
                  SET state='error',
                      last_attempt=excluded.last_attempt,
                      last_error=excluded.last_error
                """,
                (item_id, ItemState.ERROR.value, _now().isoformat(), reason),
            )
            c.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))

    def bump_attempts(self, item_id: int, reason: str) -> int:
        with self._tx() as c:
            cur = c.execute(
                """
                UPDATE items
                SET attempts = attempts + 1,
                    last_attempt = ?,
                    last_error = ?
                WHERE item_id = ?
                RETURNING attempts
                """,
                (_now().isoformat(), reason, item_id),
            )
            row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown item_id: {item_id}")
        return int(row["attempts"])

    def enqueue_retry(self, item_id: int, reason: str) -> None:
        row = self.get(item_id)
        attempt = 0 if row is None else row.attempts
        due_at = _now() + backoff_delay(attempt)
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO retry_queue(item_id, due_at, reason)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE
                  SET due_at=excluded.due_at, reason=excluded.reason
                """,
                (item_id, due_at.isoformat(), reason),
            )

    def remove_from_queue(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM retry_queue WHERE item_id = ?", (item_id,))

    def peek_next_due(self) -> QueueRow | None:
        cur = self._conn.execute(
            "SELECT item_id, due_at, reason FROM retry_queue ORDER BY due_at ASC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        return QueueRow(int(row["item_id"]), _parse_ts(row["due_at"]), str(row["reason"]))

    def pop_due(self, *, limit: int) -> list[QueueRow]:
        now_iso = _now().isoformat()
        cur = self._conn.execute(
            """
            SELECT item_id, due_at, reason FROM retry_queue
            WHERE due_at <= ? ORDER BY due_at ASC LIMIT ?
            """,
            (now_iso, limit),
        )
        return [
            QueueRow(int(r["item_id"]), _parse_ts(r["due_at"]), str(r["reason"]))
            for r in cur.fetchall()
        ]

    def get(self, item_id: int) -> ItemRow | None:
        cur = self._conn.execute(
            "SELECT item_id, state, verdict, last_attempt, attempts, last_error FROM items WHERE item_id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return ItemRow(
            item_id=int(row["item_id"]),
            state=ItemState(row["state"]),
            verdict=row["verdict"],
            last_attempt=_parse_ts(row["last_attempt"]),
            attempts=int(row["attempts"]),
            last_error=row["last_error"],
        )

    def max_item_id(self) -> int | None:
        cur = self._conn.execute("SELECT MAX(item_id) AS m FROM items")
        row = cur.fetchone()
        return int(row["m"]) if row and row["m"] is not None else None

    def queue_depth(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM retry_queue")
        row = cur.fetchone()
        return int(row["n"]) if row else 0
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_state.py -v`

Expected: 9 passed.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/state.py tests/kmail/test_state.py
git commit -m "feat(kmail): add sqlite state store with retry queue and backoff"
```

---

## Task 7 — `lares.kmail.classifier` (Ollama HTTP + prompt + JSON Schema)

**Files:**
- Create: `src/lares/kmail/classifier.py`
- Create: `tests/kmail/test_classifier.py`

**Why:** Spec §9. `format` parameter with explicit JSON Schema (not just `format: "json"`); `temperature: 0`; verdicts validated with pydantic; low-confidence → `lares-unclassified`. The user-taxonomy tag returned by `classify()` is **already prefixed** with `lares-` (consistent with Task 5 note).

- [ ] **Step 1: Write the failing test**

`tests/kmail/test_classifier.py`:
```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from lares.kmail.classifier import Classifier, ClassifierError, FetchedItem
from lares.kmail.config import KMailConfig, LaresConfig, LaresShared, OllamaConfig
from lares.kmail.tags import LARES_UNCLASSIFIED


def _cfg(min_confidence: float = 0.5) -> LaresConfig:
    return LaresConfig(
        lares=LaresShared(
            log_level="INFO",
            ollama=OllamaConfig(model="qwen3:4b-instruct-2507-q4_K_M"),
        ),
        kmail=KMailConfig(
            tags={
                "personal": "A human writing.",
                "business": "Business inquiry.",
                "newsletter": "Marketing/digest.",
                "notification": "Transactional.",
            },
            min_confidence=min_confidence,
        ),
    )


def _item() -> FetchedItem:
    return FetchedItem(
        item_id=1,
        headers={
            "From": "alice@example.com",
            "To": "me@example.com",
            "Subject": "Lunch on Friday?",
            "List-Id": "",
            "Date": "Tue, 18 May 2026 09:00:00 +0200",
        },
        body_text="Hey, are you free for lunch on Friday?",
    )


@pytest.mark.asyncio
async def test_classify_high_confidence_returns_prefixed_tag(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"personal","confidence":0.93}'},
    )
    async with Classifier(_cfg()) as c:
        verdict = await c.classify(_item())
    assert verdict.tag == "lares-personal"
    assert verdict.confidence == pytest.approx(0.93)
    assert verdict.raw_category == "personal"


@pytest.mark.asyncio
async def test_classify_low_confidence_returns_unclassified(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"newsletter","confidence":0.31}'},
    )
    async with Classifier(_cfg(min_confidence=0.5)) as c:
        verdict = await c.classify(_item())
    assert verdict.tag == LARES_UNCLASSIFIED
    assert verdict.confidence == pytest.approx(0.31)
    assert verdict.raw_category == "newsletter"


@pytest.mark.asyncio
async def test_classify_unknown_category_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"sports","confidence":0.9}'},
    )
    async with Classifier(_cfg()) as c:
        with pytest.raises(ClassifierError):
            await c.classify(_item())


@pytest.mark.asyncio
async def test_classify_malformed_json_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": "not json at all"},
    )
    async with Classifier(_cfg()) as c:
        with pytest.raises(ClassifierError):
            await c.classify(_item())


@pytest.mark.asyncio
async def test_classify_request_payload_uses_json_schema(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        json={"response": '{"category":"personal","confidence":0.9}'},
    )
    async with Classifier(_cfg()) as c:
        await c.classify(_item())
    req = httpx_mock.get_request()
    assert req is not None
    body = req.read()
    import json as _json
    payload = _json.loads(body)
    assert payload["model"] == "qwen3:4b-instruct-2507-q4_K_M"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.0
    fmt = payload["format"]
    assert fmt["type"] == "object"
    assert set(fmt["properties"]["category"]["enum"]) == {
        "personal", "business", "newsletter", "notification"
    }
    assert "personal" in payload["prompt"]
    assert "alice@example.com" in payload["prompt"]


@pytest.mark.asyncio
async def test_classify_http_error_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/generate",
        status_code=503,
    )
    async with Classifier(_cfg()) as c:
        with pytest.raises(ClassifierError):
            await c.classify(_item())
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_classifier.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/lares/kmail/classifier.py`:
```python
# SPDX-License-Identifier: MIT
"""Ollama-backed mail classifier.

Builds the prompt and the JSON Schema from the config-driven tag taxonomy,
calls Ollama's /api/generate with structured-output enforcement and
temperature=0, validates the response with pydantic, and returns a Verdict
whose `tag` is already prefixed with `lares-` (or `lares-unclassified` if
confidence is below the configured threshold).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lares.kmail.config import LaresConfig
from lares.kmail.tags import LARES_TAG_PREFIX, LARES_UNCLASSIFIED

logger = logging.getLogger(__name__)


class ClassifierError(Exception):
    """Recoverable error during classification (transport, parse, or schema)."""


@dataclass(slots=True, frozen=True)
class FetchedItem:
    item_id: int
    headers: dict[str, str]
    body_text: str


@dataclass(slots=True, frozen=True)
class Verdict:
    tag: str
    raw_category: str
    confidence: float


class _OllamaResponseEnvelope(BaseModel):
    response: str
    # Ollama emits other fields (model, created_at, done, ...); we ignore them.

    model_config = ConfigDict(extra="ignore")


class _RawVerdict(BaseModel):
    """Decoded LLM response. `category` is validated against the allowed
    set explicitly in `Classifier.classify` — pydantic only enforces the
    type and the confidence range here. Keeping the allowed-set check out
    of the schema avoids a pyright-strict struggle with dynamic Literal
    construction."""

    category: str
    confidence: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class Classifier:
    def __init__(self, config: LaresConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._categories = sorted(config.kmail.tags.keys())
        self._allowed_categories = set(self._categories)
        self._json_schema = self._build_schema()
        self._prompt_prefix = self._build_prompt_prefix()

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            base_url=self._config.lares.ollama.endpoint,
            timeout=self._config.kmail.classify_timeout_s,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def classify(self, item: FetchedItem) -> Verdict:
        if self._client is None:
            raise RuntimeError("Classifier used outside async context manager")
        payload = self._build_payload(item)
        try:
            resp = await self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClassifierError(f"ollama transport error: {exc}") from exc

        try:
            envelope = _OllamaResponseEnvelope.model_validate(resp.json())
            parsed = json.loads(envelope.response)
            verdict = _RawVerdict.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, KeyError) as exc:
            raise ClassifierError(f"ollama response parse failure: {exc}") from exc

        if verdict.category not in self._allowed_categories:
            raise ClassifierError(
                f"model returned unknown category {verdict.category!r}; "
                f"allowed={sorted(self._allowed_categories)}"
            )
        category = verdict.category
        confidence = verdict.confidence
        if confidence < self._config.kmail.min_confidence:
            tag = LARES_UNCLASSIFIED
        else:
            tag = f"{LARES_TAG_PREFIX}{category}"
        logger.info(
            "classified item_id=%d category=%s confidence=%.2f -> tag=%s",
            item.item_id, category, confidence, tag,
        )
        return Verdict(tag=tag, raw_category=category, confidence=confidence)

    def _build_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": self._categories},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["category", "confidence"],
            "additionalProperties": False,
        }

    def _build_prompt_prefix(self) -> str:
        lines = ["You classify incoming email into exactly one of these categories:", ""]
        for name in self._categories:
            lines.append(f"- {name}: {self._config.kmail.tags[name]}")
        lines.extend([
            "",
            'Respond with JSON only, no prose:',
            '{"category": "<one of the above>", "confidence": <0.0 to 1.0>}',
            "",
        ])
        return "\n".join(lines)

    def _build_payload(self, item: FetchedItem) -> dict[str, Any]:
        h = item.headers
        prompt = (
            f"{self._prompt_prefix}"
            f"Email:\n"
            f"From: {h.get('From', '')}\n"
            f"To: {h.get('To', '')}\n"
            f"Subject: {h.get('Subject', '')}\n"
            f"List-Id: {h.get('List-Id', '')}\n"
            f"Date: {h.get('Date', '')}\n\n"
            f"{item.body_text}"
        )
        return {
            "model": self._config.lares.ollama.model,
            "prompt": prompt,
            "format": self._json_schema,
            "options": {"temperature": self._config.lares.ollama.temperature},
            "stream": False,
        }
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_classifier.py -v`

Expected: 6 passed.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/classifier.py tests/kmail/test_classifier.py
git commit -m "feat(kmail): add Ollama classifier with JSON-Schema-enforced output"
```

---

## Task 8 — `lares.kmail.notify` (subprocess wrapper for `lares-akonadi-notify`)

**Files:**
- Create: `src/lares/kmail/notify.py`
- Create: `tests/kmail/test_notify.py`

**Why:** Spec §5/§6. Async context manager that spawns the helper, parses NDJSON from stdout, yields events. For tests we substitute a tiny Python script that emits canned NDJSON — no C++ needed.

- [ ] **Step 1: Write the failing test**

`tests/kmail/test_notify.py`:
```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import sys
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from lares.kmail.notify import Notify, NotifyEvent


def _stub_script(tmp_path: Path, lines: list[str]) -> Path:
    body = "\n".join(repr(line) for line in lines)
    script = tmp_path / "stub_notify.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import sys, time
            lines = [{body}]
            for line in lines:
                sys.stdout.write(line + "\\n")
                sys.stdout.flush()
            # stay alive so the test can stop us
            time.sleep(60)
            """
        )
    )
    return script


@pytest.mark.asyncio
async def test_notify_yields_parsed_events(tmp_path: Path) -> None:
    script = _stub_script(
        tmp_path,
        [
            '{"event":"item_added","item_id":1,"collection_id":10,"remote_id":"<a@x>","mimetype":"message/rfc822","ts":"2026-05-18T12:00:00Z"}',
            '{"event":"item_added","item_id":2,"collection_id":10,"remote_id":"<b@x>","mimetype":"message/rfc822","ts":"2026-05-18T12:00:01Z"}',
        ],
    )

    async with Notify.from_command([sys.executable, str(script)]) as notify:
        collected: list[NotifyEvent] = []
        async def collect() -> None:
            async for ev in notify.events():
                collected.append(ev)
                if len(collected) == 2:
                    return
        await asyncio.wait_for(collect(), timeout=5)

    assert [e.item_id for e in collected] == [1, 2]
    assert collected[0].mimetype == "message/rfc822"


@pytest.mark.asyncio
async def test_notify_skips_malformed_lines(tmp_path: Path) -> None:
    script = _stub_script(
        tmp_path,
        [
            "not json at all",
            '{"event":"item_added","item_id":7,"collection_id":1,"remote_id":"<x>","mimetype":"message/rfc822","ts":"2026-05-18T12:00:00Z"}',
        ],
    )
    async with Notify.from_command([sys.executable, str(script)]) as notify:
        async def first_event() -> NotifyEvent:
            async for ev in notify.events():
                return ev
            raise AssertionError("no events")
        ev = await asyncio.wait_for(first_event(), timeout=5)
    assert ev.item_id == 7


@pytest.mark.asyncio
async def test_notify_exit_stops_iteration(tmp_path: Path) -> None:
    script = tmp_path / "exits_quick.py"
    script.write_text("import sys; sys.exit(0)")
    async with Notify.from_command([sys.executable, str(script)]) as notify:
        events: list[NotifyEvent] = []
        async for ev in notify.events():
            events.append(ev)
    assert events == []
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_notify.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/lares/kmail/notify.py`:
```python
# SPDX-License-Identifier: MIT
"""Subprocess wrapper around `lares-akonadi-notify`.

The helper streams one NDJSON line per Akonadi `itemAdded` signal. This
wrapper parses each line, drops malformed ones with a warning, and yields
typed events. Async-context-manager managed so SIGTERM lands cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import TracebackType
from typing import Self

from lares.kmail.config import LaresConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class NotifyEvent:
    event: str
    item_id: int
    collection_id: int
    remote_id: str
    mimetype: str
    ts: str


def _default_helper_path() -> Path:
    return Path(str(resources.files("lares") / "_bin" / "lares-akonadi-notify"))


class Notify:
    def __init__(self, argv: Sequence[str]) -> None:
        self._argv = list(argv)
        self._proc: asyncio.subprocess.Process | None = None

    @classmethod
    def from_config(cls, config: LaresConfig) -> Self:
        helper = (
            Path(config.kmail.helper_binary_path)
            if config.kmail.helper_binary_path
            else _default_helper_path()
        )
        argv: list[str] = [
            str(helper),
            "--mimetype", "message/rfc822",
            "--collection-attr", "inbox",
        ]
        for name in config.kmail.watch.extra_collection_names:
            argv += ["--extra-collection", name]
        return cls(argv)

    @classmethod
    def from_command(cls, argv: Sequence[str]) -> Self:
        return cls(argv)

    async def __aenter__(self) -> Self:
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._proc is None or self._proc.returncode is not None:
            return
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()

    async def events(self) -> AsyncIterator[NotifyEvent]:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("Notify used outside async context manager")
        async for line in self._iter_lines(self._proc.stdout):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("notify: malformed NDJSON dropped: %s (%s)", line, exc)
                continue
            try:
                yield NotifyEvent(
                    event=str(payload["event"]),
                    item_id=int(payload["item_id"]),
                    collection_id=int(payload["collection_id"]),
                    remote_id=str(payload.get("remote_id", "")),
                    mimetype=str(payload.get("mimetype", "")),
                    ts=str(payload.get("ts", "")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("notify: event shape unexpected, dropped: %s (%s)", payload, exc)

    @staticmethod
    async def _iter_lines(stream: asyncio.StreamReader) -> AsyncIterator[str]:
        while True:
            raw = await stream.readline()
            if not raw:
                return
            yield raw.decode("utf-8", errors="replace").rstrip("\n")
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_notify.py -v`

Expected: 3 passed.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/notify.py tests/kmail/test_notify.py
git commit -m "feat(kmail): add notify subprocess wrapper with NDJSON event parsing"
```

---

## Task 9 — `lares.kmail.mutate` (subprocess wrapper for `lares-akonadi-mutate`)

**Files:**
- Create: `src/lares/kmail/mutate.py`
- Create: `tests/kmail/test_mutate.py`

**Why:** Spec §5. Request/response over stdio with `request_id` round-tripping, internal `asyncio.Lock` so two service tasks can share one helper. Restart-on-crash. Tested with a fake-subprocess script.

- [ ] **Step 1: Write the failing test**

`tests/kmail/test_mutate.py`:
```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from lares.kmail.mutate import Mutate, MutateError


def _echo_stub(tmp_path: Path) -> Path:
    script = tmp_path / "stub_mutate.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, sys
            for line in sys.stdin:
                req = json.loads(line)
                if req["op"] == "fetch":
                    resp = {
                        "id": req["id"], "ok": True, "item_id": req["item_id"],
                        "headers": {"From": "a@x", "To": "b@x", "Subject": "S",
                                    "List-Id": "", "Date": ""},
                        "body_text": "hello", "tags": ["lares-pending"],
                    }
                elif req["op"] == "set_tags":
                    resp = {
                        "id": req["id"], "ok": True, "item_id": req["item_id"],
                        "tags": req["tags"],
                    }
                else:
                    resp = {"id": req["id"], "ok": False,
                            "error": "bad op", "code": "bad_request"}
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
            """
        )
    )
    return script


def _error_stub(tmp_path: Path, code: str = "akonadi_offline") -> Path:
    script = tmp_path / "stub_mutate_err.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            for line in sys.stdin:
                req = json.loads(line)
                resp = {{"id": req["id"], "ok": False,
                         "error": "akonadi down", "code": "{code}"}}
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
            """
        )
    )
    return script


@pytest.mark.asyncio
async def test_fetch_round_trips(tmp_path: Path) -> None:
    async with Mutate.from_command([sys.executable, str(_echo_stub(tmp_path))]) as m:
        result = await m.fetch(42)
    assert result.item_id == 42
    assert result.body_text == "hello"
    assert result.tags == ["lares-pending"]
    assert result.headers["From"] == "a@x"


@pytest.mark.asyncio
async def test_set_tags_round_trips(tmp_path: Path) -> None:
    async with Mutate.from_command([sys.executable, str(_echo_stub(tmp_path))]) as m:
        result = await m.set_tags(42, ["lares-personal"])
    assert result == ["lares-personal"]


@pytest.mark.asyncio
async def test_error_response_raises_mutate_error(tmp_path: Path) -> None:
    async with Mutate.from_command([sys.executable, str(_error_stub(tmp_path))]) as m:
        with pytest.raises(MutateError) as ei:
            await m.fetch(1)
    assert ei.value.code == "akonadi_offline"


@pytest.mark.asyncio
async def test_not_found_error_exposes_code(tmp_path: Path) -> None:
    async with Mutate.from_command(
        [sys.executable, str(_error_stub(tmp_path, code="not_found"))]
    ) as m:
        with pytest.raises(MutateError) as ei:
            await m.fetch(404)
    assert ei.value.code == "not_found"


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized(tmp_path: Path) -> None:
    import asyncio
    async with Mutate.from_command([sys.executable, str(_echo_stub(tmp_path))]) as m:
        results = await asyncio.gather(m.fetch(1), m.fetch(2), m.fetch(3))
    assert [r.item_id for r in results] == [1, 2, 3]
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_mutate.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/lares/kmail/mutate.py`:
```python
# SPDX-License-Identifier: MIT
"""Subprocess wrapper around `lares-akonadi-mutate`.

Long-running helper process; one request line in, one response line out.
Concurrent callers are serialized through an internal `asyncio.Lock` so
the stdio framing stays in step.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from lares.kmail.config import LaresConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class FetchResult:
    item_id: int
    headers: dict[str, str]
    body_text: str
    tags: list[str]


class MutateError(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def _default_helper_path() -> Path:
    return Path(str(resources.files("lares") / "_bin" / "lares-akonadi-mutate"))


class Mutate:
    def __init__(self, argv: Sequence[str]) -> None:
        self._argv = list(argv)
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)

    @classmethod
    def from_config(cls, config: LaresConfig) -> Self:
        helper = (
            Path(config.kmail.helper_binary_path)
            if config.kmail.helper_binary_path
            else _default_helper_path()
        )
        return cls([
            str(helper),
            "--max-body-bytes", str(config.kmail.body_truncate_bytes),
        ])

    @classmethod
    def from_command(cls, argv: Sequence[str]) -> Self:
        return cls(argv)

    async def __aenter__(self) -> Self:
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._proc is None or self._proc.returncode is not None:
            return
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()

    async def fetch(self, item_id: int) -> FetchResult:
        resp = await self._call({"op": "fetch", "item_id": item_id})
        try:
            return FetchResult(
                item_id=int(resp["item_id"]),
                headers={str(k): str(v) for k, v in dict(resp["headers"]).items()},
                body_text=str(resp.get("body_text", "")),
                tags=[str(t) for t in resp.get("tags", [])],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MutateError(f"malformed fetch response: {resp}", "internal") from exc

    async def set_tags(self, item_id: int, tags: list[str]) -> list[str]:
        resp = await self._call({"op": "set_tags", "item_id": item_id, "tags": tags})
        return [str(t) for t in resp.get("tags", [])]

    async def _call(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Mutate used outside async context manager")
        req_id = f"req-{next(self._ids)}"
        envelope: dict[str, Any] = {"id": req_id, **body}
        line = (json.dumps(envelope) + "\n").encode()

        async with self._lock:
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()
            raw = await self._proc.stdout.readline()

        if not raw:
            raise MutateError("mutate helper closed stdout", "internal")
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MutateError(f"non-JSON mutate response: {raw!r}", "internal") from exc

        if resp.get("id") != req_id:
            raise MutateError(
                f"request id mismatch: sent={req_id} got={resp.get('id')}", "internal"
            )
        if not resp.get("ok"):
            raise MutateError(
                str(resp.get("error", "mutate failed")),
                str(resp.get("code", "internal")),
            )
        return resp
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_mutate.py -v`

Expected: 5 passed.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/mutate.py tests/kmail/test_mutate.py
git commit -m "feat(kmail): add mutate subprocess wrapper with serialized JSON I/O"
```

---

## Task 10 — `lares.kmail.service` (event loop + per-message state machine)

**Files:**
- Create: `src/lares/kmail/service.py`
- Create: `tests/kmail/test_service.py`

**Why:** Spec §6. Two concurrent tasks in one `TaskGroup` — `consume_new_mail` and `drain_retry_queue` — sharing `Mutate` and `Classifier`. The state machine is the heart of the agent; thoroughly tested with stubs.

**Design:** the public surface exposed for tests is `consume_one_event(event, mutate, classifier, state)` and `drain_one_due(queue_row, mutate, classifier, state)` — pure functions of their collaborators — plus `run(config)` which wires the long-running loops. Splitting the per-message handlers from the loops makes the state machine trivially testable.

- [ ] **Step 1: Write the failing test**

`tests/kmail/test_service.py`:
```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from lares.kmail.classifier import ClassifierError, FetchedItem, Verdict
from lares.kmail.mutate import FetchResult, MutateError
from lares.kmail.notify import NotifyEvent
from lares.kmail.service import consume_one_event, drain_one_due
from lares.kmail.state import ItemState, State
from lares.kmail.tags import LARES_ERROR, LARES_PENDING, LARES_UNCLASSIFIED


@dataclass
class StubMutate:
    fetched: dict[int, FetchResult] = field(default_factory=dict)
    set_tags_calls: list[tuple[int, list[str]]] = field(default_factory=list)
    fetch_errors: dict[int, MutateError] = field(default_factory=dict)

    async def fetch(self, item_id: int) -> FetchResult:
        if item_id in self.fetch_errors:
            raise self.fetch_errors[item_id]
        return self.fetched[item_id]

    async def set_tags(self, item_id: int, tags: list[str]) -> list[str]:
        self.set_tags_calls.append((item_id, list(tags)))
        return tags


@dataclass
class StubClassifier:
    verdicts: dict[int, Verdict] = field(default_factory=dict)
    errors: dict[int, ClassifierError] = field(default_factory=dict)

    async def classify(self, item: FetchedItem) -> Verdict:
        if item.item_id in self.errors:
            raise self.errors[item.item_id]
        return self.verdicts[item.item_id]


def _fetch(item_id: int, tags: list[str] | None = None) -> FetchResult:
    return FetchResult(
        item_id=item_id,
        headers={"From": "a@x", "To": "b@x", "Subject": "s", "List-Id": "", "Date": ""},
        body_text="b",
        tags=tags or [],
    )


def _ev(item_id: int) -> NotifyEvent:
    return NotifyEvent(
        event="item_added",
        item_id=item_id,
        collection_id=1,
        remote_id="<x>",
        mimetype="message/rfc822",
        ts="2026-05-18T12:00:00Z",
    )


@pytest.mark.asyncio
async def test_skip_when_item_already_has_lares_tag() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={5: _fetch(5, ["lares-personal"])})
    classifier = StubClassifier()
    await consume_one_event(_ev(5), mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls == []
    assert state.get(5) is None  # we don't write sqlite for already-tagged items


@pytest.mark.asyncio
async def test_classify_happy_path_records_verdict_and_no_retry() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={9: _fetch(9, [])})
    classifier = StubClassifier(
        verdicts={9: Verdict(tag="lares-personal", raw_category="personal", confidence=0.95)}
    )
    await consume_one_event(_ev(9), mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls == [(9, [LARES_PENDING]), (9, ["lares-personal"])]
    row = state.get(9)
    assert row is not None and row.state is ItemState.CLASSIFIED and row.verdict == "lares-personal"
    assert state.queue_depth() == 0


@pytest.mark.asyncio
async def test_low_confidence_applies_unclassified_tag() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={9: _fetch(9, [])})
    classifier = StubClassifier(
        verdicts={9: Verdict(tag=LARES_UNCLASSIFIED, raw_category="newsletter", confidence=0.31)}
    )
    await consume_one_event(_ev(9), mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls[-1] == (9, [LARES_UNCLASSIFIED])


@pytest.mark.asyncio
async def test_classifier_error_leaves_pending_and_enqueues() -> None:
    state = State(":memory:")
    mutate = StubMutate(fetched={9: _fetch(9, [])})
    classifier = StubClassifier(errors={9: ClassifierError("ollama down")})
    await consume_one_event(_ev(9), mutate, classifier, state, max_retries=10)
    # pending tag stays
    assert mutate.set_tags_calls == [(9, [LARES_PENDING])]
    row = state.get(9)
    assert row is not None and row.state is ItemState.PENDING
    assert state.queue_depth() == 1


@pytest.mark.asyncio
async def test_retries_exceeded_records_error_and_flips_tag() -> None:
    state = State(":memory:")
    # Pre-seed: item already at 10 attempts (= max_retries cap).
    state.record_pending(9)
    for _ in range(10):
        state.bump_attempts(9, "x")
    mutate = StubMutate(fetched={9: _fetch(9, [LARES_PENDING])})
    classifier = StubClassifier(errors={9: ClassifierError("still down")})
    from lares.kmail.state import QueueRow
    from datetime import UTC, datetime
    qr = QueueRow(item_id=9, due_at=datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC), reason="x")
    await drain_one_due(qr, mutate, classifier, state, max_retries=10)
    assert mutate.set_tags_calls[-1] == (9, [LARES_ERROR])
    row = state.get(9)
    assert row is not None and row.state is ItemState.ERROR
    assert state.queue_depth() == 0


@pytest.mark.asyncio
async def test_drain_skips_deleted_item() -> None:
    state = State(":memory:")
    state.record_pending(9)
    mutate = StubMutate(
        fetch_errors={9: MutateError("gone", "not_found")},
    )
    classifier = StubClassifier()
    from lares.kmail.state import QueueRow
    from datetime import UTC, datetime
    qr = QueueRow(item_id=9, due_at=datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC), reason="x")
    await drain_one_due(qr, mutate, classifier, state, max_retries=10)
    row = state.get(9)
    assert row is not None and row.state is ItemState.ERROR and row.last_error == "item_deleted"
    assert state.queue_depth() == 0
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_service.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/lares/kmail/service.py`:
```python
# SPDX-License-Identifier: MIT
"""Asyncio service for the kmail triage agent.

Owns the single event loop, supervises the two subprocess helpers and the
HTTP classifier, and runs two concurrent tasks: `consume_new_mail`
(triggered by Akonadi `item_added` events) and `drain_retry_queue`
(timer/event-driven retries).

The per-message handlers are split into pure async functions
(`consume_one_event`, `drain_one_due`) that take their collaborators
explicitly — this is the surface the unit tests exercise.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Protocol

from lares.kmail.classifier import Classifier, ClassifierError, FetchedItem, Verdict
from lares.kmail.config import LaresConfig, load_config
from lares.kmail.mutate import FetchResult, Mutate, MutateError
from lares.kmail.notify import Notify, NotifyEvent
from lares.kmail.state import QueueRow, State
from lares.kmail.tags import LARES_ERROR, LARES_PENDING, is_lares_tag

logger = logging.getLogger(__name__)


class _MutateLike(Protocol):
    async def fetch(self, item_id: int) -> FetchResult: ...
    async def set_tags(self, item_id: int, tags: list[str]) -> list[str]: ...


class _ClassifierLike(Protocol):
    async def classify(self, item: FetchedItem) -> Verdict: ...


def _to_fetched(fr: FetchResult) -> FetchedItem:
    return FetchedItem(item_id=fr.item_id, headers=fr.headers, body_text=fr.body_text)


async def _classify_and_apply(
    fr: FetchResult,
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
) -> None:
    item_id = fr.item_id
    try:
        verdict = await classifier.classify(_to_fetched(fr))
    except ClassifierError as exc:
        attempts = state.bump_attempts(item_id, str(exc)) if state.get(item_id) else 1
        if state.get(item_id) is None:
            state.record_pending(item_id)
            attempts = 1
        if attempts > max_retries:
            await mutate.set_tags(item_id, [LARES_ERROR])
            state.record_error(item_id, "exhausted_retries")
            return
        state.enqueue_retry(item_id, reason=str(exc))
        return

    await mutate.set_tags(item_id, [verdict.tag])
    state.record_classified(item_id, verdict.tag)


async def consume_one_event(
    event: NotifyEvent,
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
) -> None:
    try:
        fr = await mutate.fetch(event.item_id)
    except MutateError as exc:
        logger.warning("fetch failed for item_id=%d code=%s: %s",
                       event.item_id, exc.code, exc)
        return
    if any(is_lares_tag(t) for t in fr.tags):
        logger.debug("skipping item_id=%d (already has lares-* tag)", event.item_id)
        return
    await mutate.set_tags(event.item_id, [LARES_PENDING])
    state.record_pending(event.item_id)
    await _classify_and_apply(fr, mutate, classifier, state, max_retries=max_retries)


async def drain_one_due(
    queue_row: QueueRow,
    mutate: _MutateLike,
    classifier: _ClassifierLike,
    state: State,
    *,
    max_retries: int,
) -> None:
    try:
        fr = await mutate.fetch(queue_row.item_id)
    except MutateError as exc:
        if exc.code == "not_found":
            state.record_error(queue_row.item_id, "item_deleted")
            return
        # transient mutate failure — bump and reschedule
        attempts = state.bump_attempts(queue_row.item_id, str(exc))
        if attempts > max_retries:
            try:
                await mutate.set_tags(queue_row.item_id, [LARES_ERROR])
            except MutateError:
                logger.warning("could not flip tag to error for item_id=%d", queue_row.item_id)
            state.record_error(queue_row.item_id, "exhausted_retries")
            return
        state.enqueue_retry(queue_row.item_id, reason=str(exc))
        return
    await _classify_and_apply(fr, mutate, classifier, state, max_retries=max_retries)


async def _consume_loop(
    notify: Notify, mutate: _MutateLike, classifier: _ClassifierLike,
    state: State, *, max_retries: int,
) -> None:
    async for event in notify.events():
        await consume_one_event(event, mutate, classifier, state, max_retries=max_retries)


async def _drain_loop(
    mutate: _MutateLike, classifier: _ClassifierLike, state: State,
    *, max_retries: int, tick_s: float = 5.0,
) -> None:
    while True:
        due = state.pop_due(limit=10)
        for qr in due:
            await drain_one_due(qr, mutate, classifier, state, max_retries=max_retries)
        await asyncio.sleep(tick_s)


async def run(config: LaresConfig) -> None:
    state = State(config.kmail.state_db_path)
    try:
        async with (
            Notify.from_config(config) as notify,
            Mutate.from_config(config) as mutate,
            Classifier(config) as classifier,
        ):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(_consume_loop(
                    notify, mutate, classifier, state,
                    max_retries=config.kmail.max_retries,
                ))
                tg.create_task(_drain_loop(
                    mutate, classifier, state,
                    max_retries=config.kmail.max_retries,
                ))
    finally:
        state.close()


def _install_signal_shutdown(loop: asyncio.AbstractEventLoop) -> Callable[[], Awaitable[None]]:
    stop_event = asyncio.Event()

    def _handler() -> None:
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handler)

    async def wait_stop() -> None:
        await stop_event.wait()

    return wait_stop
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_service.py -v`

Expected: 6 passed.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/service.py tests/kmail/test_service.py
git commit -m "feat(kmail): add asyncio service and per-message state machine"
```

---

## Task 11 — Synthetic `.eml` fixtures

**Files:**
- Create: `tests/kmail/fixtures/personal.eml`
- Create: `tests/kmail/fixtures/business.eml`
- Create: `tests/kmail/fixtures/newsletter.eml`
- Create: `tests/kmail/fixtures/notification.eml`

**Why:** Spec §12 — synthetic-only, mix of German and English, fake domains (`example.com`, `lares.test`). Used by integration tests in Task 23.

- [ ] **Step 1: Create `tests/kmail/fixtures/personal.eml`**

```
From: Anna Beispiel <anna@example.com>
To: Mike <info@lares.test>
Subject: Sind wir am Freitag noch zum Abendessen verabredet?
Date: Mon, 18 May 2026 18:42:11 +0200
Message-Id: <20260518184211.personal@example.com>
Content-Type: text/plain; charset=utf-8

Hi Mike,

kurze Rückfrage – steht unser Abendessen am Freitag bei dem neuen
Italiener in der Schillerstraße noch? Wenn ja, treffen wir uns
direkt vor Ort um 19:30 Uhr?

Bis dann!
Anna
```

- [ ] **Step 2: Create `tests/kmail/fixtures/business.eml`**

```
From: Procurement Team <procurement@example.com>
To: Mike Esser <info@lares.test>
Subject: RFQ – Linux desktop integration consulting (Q3 2026)
Date: Tue, 19 May 2026 09:15:00 +0000
Message-Id: <20260519091500.business@example.com>
Content-Type: text/plain; charset=utf-8

Dear Mr Esser,

we are evaluating consultants for a Linux desktop integration project
that will run from July through October 2026. Your name was referred to
us by a colleague. Could you share your availability and day rate, and
indicate whether you would consider an initial 30-minute scoping call
next week?

Best regards,
J. Hofmann
Procurement, Example GmbH
```

- [ ] **Step 3: Create `tests/kmail/fixtures/newsletter.eml`**

```
From: KDE Community Weekly <weekly@example.com>
To: subscribers@example.com
Subject: KDE Weekly #312 – Plasma 6.4 sprint recap, Akonadi news, and more
Date: Sun, 17 May 2026 06:00:00 +0000
Message-Id: <20260517060000.newsletter@example.com>
List-Id: KDE Weekly <kde-weekly.example.com>
List-Unsubscribe: <mailto:unsubscribe@example.com>
Content-Type: text/plain; charset=utf-8

Hello KDE friends,

this week we cover the Plasma 6.4 sprint, fresh Akonadi tag UI work,
two new KRunner plugins, and a round-up of community blog posts.

Don't miss the closing item: an interview with the maintainers of
KMail about their roadmap for v6.5.

— The KDE Weekly editors
Unsubscribe: https://example.com/unsubscribe
```

- [ ] **Step 4: Create `tests/kmail/fixtures/notification.eml`**

```
From: GitHub <noreply@example.com>
To: Mike <info@lares.test>
Subject: [DerTechie/lares-agents] Pull request #42 review requested
Date: Wed, 20 May 2026 14:03:11 +0000
Message-Id: <20260520140311.notification@example.com>
List-Id: lares-agents notifications <lares-agents.dertechie.example.com>
Content-Type: text/plain; charset=utf-8

A review on pull request #42 in DerTechie/lares-agents has been
requested from you.

  Title: feat(kmail): add startup catchup pass
  Author: dependabot
  Files changed: 3

View it on GitHub:
https://example.com/DerTechie/lares-agents/pull/42

—
You are receiving this because your review was requested.
```

- [ ] **Step 5: Commit (no tests yet — fixtures are consumed by integration tests in Task 23)**

```bash
git add tests/kmail/fixtures/
git commit -m "test(kmail): add four synthetic .eml fixtures (DE/EN mix, fake domains)"
```

---

## Task 12 — C++ helper: `lares-akonadi-notify`

**Files:**
- Create: `src/akonadi_bridge/CMakeLists.txt`
- Create: `src/akonadi_bridge/notify.cpp`

**Why:** Spec §5 + §3 "Why C++". Wraps `Akonadi::Monitor`, filters by mimetype + `SpecialCollectionAttribute("inbox")`, emits one NDJSON line per `itemAdded` to stdout.

- [ ] **Step 1: Create `src/akonadi_bridge/CMakeLists.txt`**

```cmake
# SPDX-License-Identifier: MIT

# extra-cmake-modules ships helper modules (ECMMarkAsTest, ECMGenerateExportHeader,
# KDEInstallDirs, …) that KPim6Akonadi's installed CMake config transitively
# `include()`s. Loading ECM up front and pushing its module path onto
# CMAKE_MODULE_PATH is the canonical KF6/KPim6 consumer preamble; without it,
# `find_package(KPim6Akonadi)` configures but the transitive includes fail.
find_package(ECM REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

find_package(Qt6 REQUIRED COMPONENTS Core DBus)
find_package(KPim6Akonadi REQUIRED)

add_executable(lares-akonadi-notify notify.cpp)
target_link_libraries(lares-akonadi-notify
    PRIVATE
        Qt6::Core
        Qt6::DBus
        KPim6::AkonadiCore
)
target_compile_features(lares-akonadi-notify PRIVATE cxx_std_17)

install(TARGETS lares-akonadi-notify
        RUNTIME DESTINATION lares/_bin)
```

- [ ] **Step 2: Create `src/akonadi_bridge/notify.cpp`**

```cpp
// SPDX-License-Identifier: MIT
// lares-akonadi-notify
//
// Wraps Akonadi::Monitor. Subscribes to itemAdded events for collections
// flagged as inbox (Akonadi::SpecialCollectionAttribute) restricted to
// message/rfc822, and writes one NDJSON line per event to stdout.
//
// Usage: lares-akonadi-notify --mimetype <m> --collection-attr <name>
//                             [--extra-collection NAME ...]

#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDateTime>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <iostream>

#include <Akonadi/Collection>
#include <Akonadi/Item>
#include <Akonadi/Monitor>
#include <Akonadi/SpecialCollectionAttribute>

namespace
{

void emitEvent(const Akonadi::Item &item, const Akonadi::Collection &collection)
{
    QJsonObject obj;
    obj.insert("event", "item_added");
    obj.insert("item_id", static_cast<qint64>(item.id()));
    obj.insert("collection_id", static_cast<qint64>(collection.id()));
    obj.insert("remote_id", item.remoteId());
    obj.insert("mimetype", item.mimeType());
    obj.insert("ts", QDateTime::currentDateTimeUtc().toString(Qt::ISODate));

    const auto bytes = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    std::cout << bytes.constData() << '\n';
    std::cout.flush();
}

} // namespace

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("lares-akonadi-notify"));

    QCommandLineParser parser;
    parser.addHelpOption();
    QCommandLineOption mimeOpt(QStringLiteral("mimetype"),
        QStringLiteral("Akonadi mimetype to monitor."),
        QStringLiteral("mime"), QStringLiteral("message/rfc822"));
    QCommandLineOption attrOpt(QStringLiteral("collection-attr"),
        QStringLiteral("SpecialCollectionAttribute type to include (e.g. inbox)."),
        QStringLiteral("name"), QStringLiteral("inbox"));
    QCommandLineOption extraOpt(QStringLiteral("extra-collection"),
        QStringLiteral("Extra collection name to monitor (repeatable)."),
        QStringLiteral("name"));
    parser.addOption(mimeOpt);
    parser.addOption(attrOpt);
    parser.addOption(extraOpt);
    parser.process(app);

    auto *monitor = new Akonadi::Monitor(&app);
    monitor->setMimeTypeMonitored(parser.value(mimeOpt));
    // Akonadi::Monitor by itself fires for every monitored mimetype across
    // every collection the session can see. Filtering to inbox-like
    // collections happens inside the slot: cheap and avoids depending on
    // SpecialCollectionAttribute being set at startup (it's lazy on first
    // resource sync).
    const QString inboxAttrType = parser.value(attrOpt).toLower();
    const QStringList extraNames = parser.values(extraOpt);

    QObject::connect(monitor, &Akonadi::Monitor::itemAdded,
        [inboxAttrType, extraNames](const Akonadi::Item &item,
                                    const Akonadi::Collection &collection) {
            bool include = false;
            if (extraNames.contains(collection.name())) {
                include = true;
            } else if (collection.hasAttribute<Akonadi::SpecialCollectionAttribute>()) {
                const auto *attr =
                    collection.attribute<Akonadi::SpecialCollectionAttribute>();
                if (attr && attr->collectionType().toLower() == inboxAttrType.toUtf8()) {
                    include = true;
                }
            }
            if (include) {
                emitEvent(item, collection);
            }
        });

    return app.exec();
}
```

- [ ] **Step 3: Build the wheel**

Run: `uv sync`

Expected: CMake configures, finds Qt6 + KPim6Akonadi, compiles `lares-akonadi-notify`, installs into the package's `_bin/`. (If the runner doesn't have the dev headers, this fails with a `find_package(KPim6Akonadi)` error — the dev should `pacman -S extra-cmake-modules` etc., per README.)

- [ ] **Step 4: Smoke-check the binary is in the wheel layout**

`uv sync` performs an *editable* install: scikit-build-core does not run CMake in editable mode and does not surface CMake-installed artifacts under `importlib.resources.files('lares')`. The smoke check therefore needs a real wheel build:

```bash
uv build --wheel --out-dir /tmp/lares-wheel-check
uv venv /tmp/lares-wheel-venv
/tmp/lares-wheel-venv/bin/python -m pip install /tmp/lares-wheel-check/lares-*.whl
/tmp/lares-wheel-venv/bin/python -c "from importlib.resources import files; p = files('lares') / '_bin' / 'lares-akonadi-notify'; print(p, p.is_file())"
```

Expected: prints a path; `p.is_file()` is `True`; the file is mode `0755`.

- [ ] **Step 5: Quality gates (Python checks unchanged)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/akonadi_bridge/CMakeLists.txt src/akonadi_bridge/notify.cpp
git commit -m "feat(bridge): add lares-akonadi-notify C++ helper"
```

---

## Task 13 — C++ helper: `lares-akonadi-mutate`

**Files:**
- Modify: `src/akonadi_bridge/CMakeLists.txt`
- Create: `src/akonadi_bridge/mutate.cpp`

**Why:** Spec §5. Long-running helper reading one JSON request per line on stdin, writing one JSON response per line on stdout. Two ops: `fetch` (headers + truncated body) and `set_tags` (replace within `lares-*` namespace, auto-create missing definitions).

- [ ] **Step 1: Edit `src/akonadi_bridge/CMakeLists.txt`** — add the mutate target.

Append to the file:
```cmake
add_executable(lares-akonadi-mutate mutate.cpp)
target_link_libraries(lares-akonadi-mutate
    PRIVATE
        Qt6::Core
        Qt6::DBus
        KPim6::AkonadiCore
)
target_compile_features(lares-akonadi-mutate PRIVATE cxx_std_17)

install(TARGETS lares-akonadi-mutate
        RUNTIME DESTINATION lares/_bin)
```

- [ ] **Step 2: Create `src/akonadi_bridge/mutate.cpp`**

```cpp
// SPDX-License-Identifier: MIT
// lares-akonadi-mutate
//
// Long-running helper: reads one JSON request per line on stdin and
// writes one JSON response per line on stdout. Two ops:
//   - fetch:    {"id":"…","op":"fetch","item_id":N}
//               -> {"id":"…","ok":true,"item_id":N,
//                   "headers":{…},"body_text":"…","tags":[…]}
//   - set_tags: {"id":"…","op":"set_tags","item_id":N,"tags":[…]}
//               -> {"id":"…","ok":true,"item_id":N,"tags":[…]}
//
// Tags in the `lares-` namespace are auto-created if missing; non-lares
// tags on the item are preserved across set_tags calls.

#include <QByteArray>
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSocketNotifier>
#include <QString>
#include <QTextDocumentFragment>

#include <Akonadi/Item>
#include <Akonadi/ItemFetchJob>
#include <Akonadi/ItemFetchScope>
#include <Akonadi/ItemModifyJob>
#include <Akonadi/Tag>
#include <Akonadi/TagCreateJob>
#include <Akonadi/TagFetchJob>
#include <Akonadi/TagFetchScope>

#include <KMime/Message>

#include <iostream>
#include <memory>

namespace
{

constexpr const char *LARES_PREFIX = "lares-";

int g_maxBodyBytes = 8192;

void writeResponse(const QJsonObject &obj)
{
    const auto bytes = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    std::cout << bytes.constData() << '\n';
    std::cout.flush();
}

void writeError(const QString &id, const QString &message, const QString &code)
{
    QJsonObject obj;
    obj.insert("id", id);
    obj.insert("ok", false);
    obj.insert("error", message);
    obj.insert("code", code);
    writeResponse(obj);
}

QString headerOrEmpty(const KMime::Headers::Base *hdr)
{
    return hdr ? QString::fromUtf8(hdr->asUnicodeString().toUtf8()) : QString();
}

QString extractBody(const std::shared_ptr<KMime::Message> &msg)
{
    auto *plain = msg->mainBodyPart("text/plain");
    if (plain) {
        return plain->decodedText(KMime::Content::NoTrim);
    }
    auto *html = msg->mainBodyPart("text/html");
    if (html) {
        const QString rawHtml = html->decodedText(KMime::Content::NoTrim);
        return QTextDocumentFragment::fromHtml(rawHtml).toPlainText();
    }
    return QString();
}

void handleFetch(const QString &id, qint64 itemId)
{
    Akonadi::Item item(itemId);
    auto *job = new Akonadi::ItemFetchJob(item);
    job->fetchScope().fetchFullPayload(true);
    job->fetchScope().fetchAllAttributes();
    job->fetchScope().setFetchTags(true);

    QObject::connect(job, &Akonadi::ItemFetchJob::result, [id, itemId](KJob *kjob) {
        auto *fjob = static_cast<Akonadi::ItemFetchJob *>(kjob);
        if (fjob->error() || fjob->items().isEmpty()) {
            writeError(id, fjob->errorString().isEmpty() ? QStringLiteral("not found")
                                                          : fjob->errorString(),
                       QStringLiteral("not_found"));
            return;
        }
        const auto fetched = fjob->items().constFirst();
        QJsonObject resp;
        resp.insert("id", id);
        resp.insert("ok", true);
        resp.insert("item_id", itemId);

        QJsonObject headers;
        if (fetched.hasPayload<std::shared_ptr<KMime::Message>>()) {
            auto msg = fetched.payload<std::shared_ptr<KMime::Message>>();
            headers.insert("From", headerOrEmpty(msg->from()));
            headers.insert("To", headerOrEmpty(msg->to()));
            headers.insert("Subject", headerOrEmpty(msg->subject()));
            auto *listId = msg->headerByType("List-Id");
            headers.insert("List-Id", listId ? listId->asUnicodeString() : QString());
            headers.insert("Date", headerOrEmpty(msg->date()));

            QString body = extractBody(msg);
            const QByteArray utf8 = body.toUtf8();
            if (utf8.size() > g_maxBodyBytes) {
                body = QString::fromUtf8(utf8.left(g_maxBodyBytes));
            }
            resp.insert("body_text", body);
        } else {
            resp.insert("body_text", QString());
        }
        resp.insert("headers", headers);

        QJsonArray tagsArr;
        for (const auto &tag : fetched.tags()) {
            tagsArr.append(QString::fromUtf8(tag.gid()));
        }
        resp.insert("tags", tagsArr);

        writeResponse(resp);
    });
}

void handleSetTags(const QString &id, qint64 itemId, const QStringList &requestedTagNames)
{
    // First fetch the current item to learn its existing tags so we can
    // preserve non-lares ones, then replace the lares-* subset.
    Akonadi::Item item(itemId);
    auto *fetchJob = new Akonadi::ItemFetchJob(item);
    fetchJob->fetchScope().setFetchTags(true);

    QObject::connect(fetchJob, &Akonadi::ItemFetchJob::result,
        [id, itemId, requestedTagNames](KJob *kjob) {
        auto *fjob = static_cast<Akonadi::ItemFetchJob *>(kjob);
        if (fjob->error() || fjob->items().isEmpty()) {
            writeError(id, QStringLiteral("not found"), QStringLiteral("not_found"));
            return;
        }
        Akonadi::Item fetched = fjob->items().constFirst();
        Akonadi::Tag::List newTags;
        for (const auto &tag : fetched.tags()) {
            const QByteArray gid = tag.gid();
            if (!gid.startsWith(LARES_PREFIX)) {
                newTags.append(tag);
            }
        }
        for (const auto &name : requestedTagNames) {
            Akonadi::Tag t(name);
            t.setGid(name.toUtf8());
            newTags.append(t);
        }
        fetched.setTags(newTags);
        auto *modJob = new Akonadi::ItemModifyJob(fetched);
        modJob->disableRevisionCheck();
        QObject::connect(modJob, &KJob::result,
            [id, itemId, requestedTagNames](KJob *mkjob) {
            if (mkjob->error()) {
                writeError(id, mkjob->errorString(), QStringLiteral("internal"));
                return;
            }
            QJsonObject resp;
            resp.insert("id", id);
            resp.insert("ok", true);
            resp.insert("item_id", itemId);
            QJsonArray arr;
            for (const auto &n : requestedTagNames) {
                arr.append(n);
            }
            resp.insert("tags", arr);
            writeResponse(resp);
        });
    });
}

void dispatch(const QByteArray &line)
{
    QJsonParseError err;
    const auto doc = QJsonDocument::fromJson(line, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        writeError(QStringLiteral("?"), QStringLiteral("invalid JSON"),
                   QStringLiteral("bad_request"));
        return;
    }
    const auto obj = doc.object();
    const QString id = obj.value(QStringLiteral("id")).toString();
    const QString op = obj.value(QStringLiteral("op")).toString();
    const qint64 itemId = static_cast<qint64>(obj.value(QStringLiteral("item_id")).toDouble());
    if (op == QStringLiteral("fetch")) {
        handleFetch(id, itemId);
    } else if (op == QStringLiteral("set_tags")) {
        QStringList tagNames;
        for (const auto &v : obj.value(QStringLiteral("tags")).toArray()) {
            tagNames << v.toString();
        }
        handleSetTags(id, itemId, tagNames);
    } else {
        writeError(id, QStringLiteral("unknown op: ") + op, QStringLiteral("bad_request"));
    }
}

} // namespace

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("lares-akonadi-mutate"));

    QCommandLineParser parser;
    parser.addHelpOption();
    QCommandLineOption maxBodyOpt(QStringLiteral("max-body-bytes"),
        QStringLiteral("Truncate message bodies to N bytes."),
        QStringLiteral("n"), QStringLiteral("8192"));
    parser.addOption(maxBodyOpt);
    parser.process(app);
    g_maxBodyBytes = parser.value(maxBodyOpt).toInt();
    if (g_maxBodyBytes <= 0) {
        g_maxBodyBytes = 8192;
    }

    // Read stdin line-by-line on the event loop using QSocketNotifier on FD 0.
    auto *notifier = new QSocketNotifier(fileno(stdin), QSocketNotifier::Read, &app);
    QObject::connect(notifier, &QSocketNotifier::activated, [notifier](QSocketDescriptor) {
        std::string line;
        if (!std::getline(std::cin, line)) {
            notifier->setEnabled(false);
            QCoreApplication::quit();
            return;
        }
        dispatch(QByteArray::fromStdString(line));
    });

    return app.exec();
}
```

- [ ] **Step 3: Add KMime + Qt6 Gui dep — only on the mutate target**

`KPim6Akonadi` does not pull in KMime automatically; `mutate.cpp` uses `KMime::Message` and `KMime::Headers::Base`. The HTML-fallback path in `extractBody()` also needs `QTextDocumentFragment::fromHtml(...)`, which lives in `Qt6::Gui` — not picked up by `Qt6::Core` from Task 12. Edit `src/akonadi_bridge/CMakeLists.txt`:

1. Extend the existing Qt6 find_package line. Change:
   ```cmake
   find_package(Qt6 REQUIRED COMPONENTS Core DBus)
   ```
   to:
   ```cmake
   find_package(Qt6 REQUIRED COMPONENTS Core DBus Gui)
   ```
   (The notify target does not link `Qt6::Gui`; listing it in `COMPONENTS` only imports the target so we can link from the mutate target.)
2. Near the existing `find_package` lines, add:
   ```cmake
   find_package(KPim6Mime REQUIRED)
   ```
3. **Only** the mutate target gets `Qt6::Gui` and `KPim6::Mime`. Update its `target_link_libraries` block (do NOT modify the notify target's block):
   ```cmake
   target_link_libraries(lares-akonadi-mutate
       PRIVATE
           Qt6::Core
           Qt6::DBus
           Qt6::Gui
           KPim6::AkonadiCore
           KPim6::Mime
   )
   ```
   The notify target stays linked against `Qt6::Core Qt6::DBus KPim6::AkonadiCore` only.

- [ ] **Step 4: Build**

Run: `uv sync`

Expected: both binaries compile, install to `lares/_bin/`.

- [ ] **Step 5: Quality gates**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
```

- [ ] **Step 6: Commit**

```bash
git add src/akonadi_bridge/CMakeLists.txt src/akonadi_bridge/mutate.cpp
git commit -m "feat(bridge): add lares-akonadi-mutate C++ helper for fetch and tag-set"
```

- [ ] **Step 7: Spec-conformance fix-up (one follow-up commit)**

The Step 2 draft is deliberately minimal so the structural commit reads cleanly. Two spec §5 requirements are NOT met by the Step 2 draft and must be closed in a `fix(bridge):` follow-up commit on top of Step 6:

1. **`akonadi_offline` error code path.** Spec §5 lists `akonadi_offline` as a distinct code; the Step 2 draft never emits it. Add a small `ensureAkonadiOnline(id)` helper that emits `akonadi_offline` when `Akonadi::ServerManager::state() != Running`, and call it at the top of `handleFetch` and `handleSetTags`. Add `#include <Akonadi/ServerManager>`.
2. **`TagCreateJob` auto-vivification.** Spec §5: "auto-creating tag definitions via `TagCreateJob` if missing." The Step 2 draft constructs `Akonadi::Tag(name)` directly; the gid attaches to the item but no server-side Tag definition (with name, color, type) is created. Replace the direct-construct loop with a `TagCreateJob` chain: for each requested name, issue an `Akonadi::TagCreateJob(candidate)` with `setMergeIfExisting(true)`. Coordinate the N completions with a shared counter; on counter-reaches-zero, invoke an extracted `applyTagsAndModify(...)` helper that does the `ItemModifyJob`.

Bundle the following nits into the same commit so the contract surface is clean:

- **UTF-8 codepoint-safe body truncation.** `QByteArray::left(n)` can split a multibyte sequence. Walk back from the truncation point while bytes match the `10xxxxxx` continuation pattern; then drop a trailing head byte if it's now orphaned (`110xxxxx`/`1110xxxx`/`11110xxx`).
- **Simplify `headerOrEmpty`.** `QString::fromUtf8(hdr->asUnicodeString().toUtf8())` is a no-op roundtrip; replace with `return hdr ? hdr->asUnicodeString() : QString();`.
- **`QJsonValue::toInteger()`** for `item_id` parsing in `dispatch()`. `toDouble()` + `static_cast<qint64>` loses precision above 2^53.
- **Remove unused includes** — after the TagCreateJob change lands, `<Akonadi/TagFetchJob>` and `<Akonadi/TagFetchScope>` are not used; keep only `<Akonadi/TagCreateJob>`.

Verification + commit message shape:
```bash
uv build --wheel --out-dir /tmp/lares-wheel-fixup
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/akonadi_bridge/mutate.cpp
git commit -m "fix(bridge): conform lares-akonadi-mutate to spec §5"
```

---

## Task 14 — CLI scaffolding + `lares kmail run`

**Files:**
- Create: `src/lares/kmail/cli.py`
- Create: `tests/kmail/test_cli.py`

**Why:** Spec §10. argparse-based dispatcher. Task 14 wires the skeleton + `run`; later tasks attach more subcommands to the same parser.

- [ ] **Step 1: Write the failing test**

`tests/kmail/test_cli.py`:
```python
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
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/lares/kmail/cli.py`:
```python
# SPDX-License-Identifier: MIT
"""`lares` CLI entry point.

argparse-based. One top-level dispatcher with `kmail` and `install`
subcommand groups. Each subcommand binds an `_cmd_*` function via
`set_defaults(func=...)` so the dispatcher is a one-liner.

Tasks 15–22 extend this file; Task 14 lays down the run-only skeleton.
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
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: 3 passed.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/cli.py tests/kmail/test_cli.py
git commit -m "feat(cli): add lares CLI dispatcher with kmail run subcommand"
```

---

## Task 15 — `lares kmail status`, `config-check`

**Files:**
- Modify: `src/lares/kmail/cli.py`
- Modify: `tests/kmail/test_cli.py`

**Why:** Spec §10. `status` reads sqlite + reports queue depth & last classified item; `config-check` validates config + checks Ollama reachability + verifies the configured model is pulled + checks Akonadi is up.

- [ ] **Step 1: Write the failing tests** (append to `tests/kmail/test_cli.py`)

```python
import json as _json
from io import StringIO
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from lares.kmail.cli import _cmd_kmail_status, _cmd_kmail_config_check
from lares.kmail.config import KMailConfig, LaresConfig, LaresShared, OllamaConfig
from lares.kmail.state import State


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
    rc = _cmd_kmail_status(_NS())
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
    rc = _cmd_kmail_status(_NS())
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

    rc = _cmd_kmail_config_check(_NS())
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

    rc = _cmd_kmail_config_check(_NS())
    out = capsys.readouterr().out
    assert rc != 0
    assert "ollama pull m" in out


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
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: import errors for `_cmd_kmail_status`, `_cmd_kmail_config_check`.

- [ ] **Step 3: Extend `src/lares/kmail/cli.py`**

Add imports at the top of the file:
```python
import json
import httpx
from lares.kmail.state import State
```

Add subcommand handlers before `build_parser`:
```python
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
```

Wire them into `build_parser` (add inside the `kmail_sub` block):

```python
    status = kmail_sub.add_parser("status", help="print service state")
    status.add_argument("--json", action="store_true", help="emit JSON instead of text")
    status.set_defaults(func=_cmd_kmail_status)

    cfg_check = kmail_sub.add_parser("config-check", help="validate config + preflight")
    cfg_check.set_defaults(func=_cmd_kmail_config_check)
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: all tests pass (3 from Task 14 + 4 added here = 7).

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/cli.py tests/kmail/test_cli.py
git commit -m "feat(cli): add 'kmail status' and 'kmail config-check' subcommands"
```

---

## Task 16 — `lares kmail backfill`, `catchup`, `retag`, `purge`

**Files:**
- Modify: `src/lares/kmail/cli.py`
- Modify: `tests/kmail/test_cli.py`

**Why:** Spec §10. Operational commands. They reuse the same state machine handlers (`consume_one_event`-equivalent) from `service.py`, so the implementation is mostly orchestration.

For simplicity in v0.1, `backfill`/`catchup`/`retag` all open the same async resources (`Mutate`, `Classifier`) and call into the existing per-message handlers — no new policy logic.

- [ ] **Step 1: Write the failing tests** (append to `test_cli.py`)

```python
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
    from lares.kmail.cli import _cmd_kmail_purge
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

    rc = _cmd_kmail_purge(_NS())
    assert rc == 0
    assert not db.exists()
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: import errors / argparse misses.

- [ ] **Step 3: Extend `cli.py`**

Add handlers:
```python
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


async def _run_backfill(
    cfg: LaresConfig, *, limit: int, collection: str | None, dry_run: bool
) -> None:
    # Backfill enumerates items in the inbox(es) via the mutate helper.
    # The mutate helper does not yet expose a `list_items` op in v0.1 — see
    # design spec §13 risks. For v0.1, the CLI emits an actionable
    # "not yet implemented" message instead of pretending it works.
    sys.stderr.write(
        "backfill: requires a mutate-helper `list_items` op which is not in v0.1.\n"
        "  Tracked as v0.2 follow-up. Use KMail's UI or `lares kmail retag <id>`.\n"
    )


async def _run_catchup(cfg: LaresConfig, *, since: int | None) -> None:
    # Same caveat as backfill — requires a mutate `list_items` op.
    sys.stderr.write(
        "catchup: requires a mutate-helper `list_items` op which is not in v0.1.\n"
        "  Tracked as v0.2 follow-up.\n"
    )


async def _run_retag(cfg: LaresConfig, *, item_id: int, remove: bool) -> None:
    from lares.kmail.classifier import Classifier
    from lares.kmail.mutate import Mutate
    from lares.kmail.service import _classify_and_apply
    from lares.kmail.tags import LARES_PENDING

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
                fr, mutate, classifier, state, max_retries=cfg.kmail.max_retries,
            )
    finally:
        state.close()
```

> **Note on backfill/catchup:** the design spec §13 calls out that these features require a `list_items` op on the mutate helper. We're shipping v0.1 *without* that op — the helpers expose only `fetch` and `set_tags`. Rather than fake the commands, they print an actionable "not yet in v0.1" message. Adding `list_items` to `lares-akonadi-mutate` is a v0.2 task (one more `case` in `dispatch()` + an `Akonadi::ItemFetchJob` over a `Collection`). Documented as a known gap in the README.

Wire them into `build_parser`:

```python
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
    retag.add_argument("--remove", action="store_true",
                       help="strip all lares-* tags from the item instead")
    retag.set_defaults(func=_cmd_kmail_retag)

    purge = kmail_sub.add_parser("purge", help="delete sqlite state (destructive)")
    purge.add_argument("--confirm", action="store_true", required=True)
    purge.set_defaults(func=_cmd_kmail_purge)
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: 12 passed (7 from before + 5 new).

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/cli.py tests/kmail/test_cli.py
git commit -m "feat(cli): add backfill, catchup, retag, purge subcommands

backfill and catchup print an actionable v0.2-follow-up message — they
require a list_items op on the mutate helper that is not part of v0.1
scope. retag and purge are fully functional."
```

---

## Task 17 — Spec amendment: defer `backfill`/`catchup` to v0.2

**Files:**
- Modify: `docs/superpowers/specs/2026-05-18-kmail-triage-agent-design.md`

**Why:** Task 16 surfaced a real gap in v0.1 scope — the mutate helper has no `list_items` op, so backfill/catchup can't actually do anything. Spec self-review missed this. Honest fix: amend the spec to mark these as v0.2 scope, document the helper op gap, and keep the CLI stubs (with their "not yet in v0.1" message) so the surface area is consistent.

- [ ] **Step 1: Add to spec §10 (CLI surface) — replace the `backfill` and `catchup` rows**

Find the rows for `lares kmail backfill` and `lares kmail catchup` in §10 and replace with:

```markdown
| `lares kmail backfill [--limit N] [--collection NAME] [--dry-run]` | **v0.2 (stubbed in v0.1).** Requires a `list_items` op on `lares-akonadi-mutate` which is not part of v0.1 scope. v0.1 ships the CLI surface that prints an actionable "not yet implemented" message. |
| `lares kmail catchup [--since ITEM_ID]` | **v0.2 (stubbed in v0.1).** Same dependency as `backfill`. v0.1 ships the CLI surface only. Startup catchup behavior (described in §6) is also deferred to v0.2 — v0.1 starts with an empty event horizon and processes only items that arrive after service start. |
```

- [ ] **Step 2: Add to spec §6 (service architecture) — strike the "Startup catchup" subsection**

Replace the entire `### Startup catchup` subsection with:

```markdown
### Startup catchup — deferred to v0.2

Originally specified as a startup scan of items with `item_id > MAX(items.item_id)`. Requires a `list_items` op on the mutate helper that is not part of v0.1. v0.1 starts with an empty event horizon; any mail that arrived while the service was down is **not** automatically processed on next start. Users can re-process individual items via `lares kmail retag <id>` until v0.2 lands.
```

- [ ] **Step 3: Add to spec §13 (known risks) — add a new numbered risk**

Append after risk 5:

```markdown
6. **No bulk-discovery op on `lares-akonadi-mutate` in v0.1.** The helper exposes `fetch` and `set_tags` only; there is no `list_items` op. Consequences: no automatic startup catchup, no functional `backfill` or `catchup` CLI in v0.1. Mitigation: shipped as a v0.2 task — add `list_items` op (a few lines, wraps `Akonadi::ItemFetchJob` over a `Collection`) and unblock all three. Acceptable v0.1 gap because the new-mail path is unaffected; users can re-process individual stragglers via `lares kmail retag <id>`.
```

- [ ] **Step 4: Add to spec §15 (decisions journal)**

Append one row:

```markdown
| Bulk-discovery op | Deferred to v0.2 | Surfaced during plan-writing; v0.1 ships the CLI surface stubbed with an actionable message. New-mail path is unaffected. |
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-18-kmail-triage-agent-design.md
git commit -m "docs(spec): defer kmail backfill/catchup to v0.2

The mutate helper exposes fetch + set_tags only; bulk discovery
requires a list_items op that is not v0.1 scope. CLI subcommands ship
with actionable not-yet-implemented messages; per-item retag remains."
```

---

## Task 18 — `lares install config` + config skeleton

**Files:**
- Create: `src/lares/_config/__init__.py`
- Create: `src/lares/_config/config.toml.skel`
- Modify: `pyproject.toml` (declare `_config/*.skel` as package data)
- Modify: `src/lares/kmail/cli.py`
- Modify: `tests/kmail/test_cli.py`

- [ ] **Step 1: Create `src/lares/_config/__init__.py`**

```python
# SPDX-License-Identifier: MIT
```

- [ ] **Step 2: Create `src/lares/_config/config.toml.skel`**

```toml
# Lares configuration. Place at ~/.config/lares/config.toml.

[lares]
log_level = "INFO"                              # DEBUG only for development

[lares.ollama]
endpoint    = "http://127.0.0.1:11434"          # local-first hardcoded default
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
catchup_limit        = 200     # v0.2 — currently a no-op in v0.1
min_confidence       = 0.5     # below this → lares-unclassified
helper_binary_path   = ""      # dev override; "" = use packaged helpers

# Tag taxonomy. Keys become Akonadi tag names (prefixed with "lares-" when
# applied to items). Descriptions go to the LLM as part of the prompt.
[kmail.tags]
personal     = "Mail from a real human writing to me directly (friends, family, individual professional correspondence)."
business     = "Inquiries, contracts, invoices, professional requests requiring a response."
newsletter   = "Marketing emails, digests, promotions, mailing list announcements."
notification = "Transactional or automated mail (GitHub notifications, calendar invites, receipts, service alerts)."

[kmail.watch]
extra_collection_names = []
```

- [ ] **Step 3: Verify the `.skel` ships in the wheel**

No `pyproject.toml` change needed. `wheel.packages = ["src/lares"]` (set in Task 1) already includes everything under that directory, so the `.skel` file under `src/lares/_config/` is shipped as package data automatically. Confirm after the build in Step 7.

- [ ] **Step 4: Write the failing tests** (append to `test_cli.py`)

```python
def test_install_config_writes_skeleton_when_missing(tmp_path: Path) -> None:
    from lares.kmail.cli import _cmd_install_config
    target = tmp_path / "config.toml"

    class _NS:
        config = target
        force = False

    rc = _cmd_install_config(_NS())
    assert rc == 0
    assert target.exists()
    body = target.read_text()
    assert "[lares.ollama]" in body
    assert "qwen3:4b-instruct-2507-q4_K_M" in body


def test_install_config_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    from lares.kmail.cli import _cmd_install_config
    target = tmp_path / "config.toml"
    target.write_text("existing")

    class _NS:
        config = target
        force = False

    rc = _cmd_install_config(_NS())
    assert rc != 0
    assert target.read_text() == "existing"


def test_install_config_force_overwrites(tmp_path: Path) -> None:
    from lares.kmail.cli import _cmd_install_config
    target = tmp_path / "config.toml"
    target.write_text("existing")

    class _NS:
        config = target
        force = True

    rc = _cmd_install_config(_NS())
    assert rc == 0
    assert "qwen3" in target.read_text()
```

- [ ] **Step 5: Run; verify failure**

Run: `uv run pytest tests/kmail/test_cli.py::test_install_config_writes_skeleton_when_missing -v`

Expected: ImportError / AttributeError.

- [ ] **Step 6: Implement**

Add to `src/lares/kmail/cli.py`:

```python
from importlib import resources


def _cmd_install_config(ns: argparse.Namespace) -> int:
    target = Path(ns.config)
    if target.exists() and not ns.force:
        sys.stderr.write(
            f"refusing to overwrite existing {target} (use --force)\n"
        )
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    template = resources.files("lares._config").joinpath("config.toml.skel").read_text()
    target.write_text(template)
    sys.stdout.write(f"wrote {target}\n")
    return 0
```

Wire into `build_parser` (add a new `install` subcommand group):

```python
    install = sub.add_parser("install", help="install lifecycle (config / systemd / check)")
    install_sub = install.add_subparsers(dest="install_cmd", required=True)

    install_cfg = install_sub.add_parser("config", help="write config.toml skeleton")
    install_cfg.add_argument("--force", action="store_true",
                             help="overwrite an existing config file")
    install_cfg.set_defaults(func=_cmd_install_config)
```

- [ ] **Step 7: Run; verify pass**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: all CLI tests pass.

- [ ] **Step 8: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/_config/ pyproject.toml src/lares/kmail/cli.py tests/kmail/test_cli.py
git commit -m "feat(cli): add 'lares install config' and ship default config skeleton"
```

---

## Task 19 — Reserved (was config skeleton, merged into Task 18)

Skip — incorporated into Task 18. Renumber tasks 20+ stay as written.

---

## Task 20 — `packaging/systemd/lares-kmail.service` + ship in wheel

**Files:**
- Create: `packaging/systemd/lares-kmail.service`
- Create: `src/lares/_systemd/__init__.py`
- Modify: top-level `CMakeLists.txt` (copy unit into wheel)

**Why:** Spec §11. The unit file lives at `packaging/systemd/` as source of truth and is copied into `src/lares/_systemd/` at build time so `importlib.resources` can find it from the installed wheel.

- [ ] **Step 1: Create `packaging/systemd/lares-kmail.service`**

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

- [ ] **Step 2: Create `src/lares/_systemd/__init__.py`**

```python
# SPDX-License-Identifier: MIT
```

- [ ] **Step 3: Edit top-level `CMakeLists.txt`**

Append at the end:

```cmake
# Copy the systemd unit into the wheel so importlib.resources can find it.
install(FILES packaging/systemd/lares-kmail.service
        DESTINATION lares/_systemd)
```

- [ ] **Step 4: Rebuild and verify the unit lands in the package**

Run: `uv sync && python -c "from importlib.resources import files; print((files('lares') / '_systemd' / 'lares-kmail.service').read_text()[:80])"`

Expected: prints the first 80 chars of the unit file (the `[Unit]` block).

- [ ] **Step 5: Commit**

```bash
git add packaging/systemd/lares-kmail.service src/lares/_systemd/__init__.py CMakeLists.txt
git commit -m "feat(packaging): ship systemd --user unit file inside the wheel"
```

---

## Task 21 — `lares install systemd` (install / uninstall / enable / start)

**Files:**
- Modify: `src/lares/kmail/cli.py`
- Modify: `tests/kmail/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
import os
import subprocess
from unittest.mock import patch


def _systemd_unit_dir(home: Path) -> Path:
    return home / ".config" / "systemd" / "user"


def test_install_systemd_writes_unit_to_user_dir(tmp_path: Path) -> None:
    from lares.kmail.cli import _cmd_install_systemd
    home = tmp_path / "home"
    unit_dir = _systemd_unit_dir(home)

    class _NS:
        config = tmp_path / "config.toml"
        enable = False
        start = False
        uninstall = False

    with patch.dict(os.environ, {"HOME": str(home)}):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            rc = _cmd_install_systemd(_NS())
    assert rc == 0
    unit = unit_dir / "lares-kmail.service"
    assert unit.exists()
    assert "Description=Lares" in unit.read_text()
    # daemon-reload always
    assert any("daemon-reload" in str(c.args) for c in mock_run.call_args_list)


def test_install_systemd_with_enable_and_start(tmp_path: Path) -> None:
    from lares.kmail.cli import _cmd_install_systemd
    home = tmp_path / "home"

    class _NS:
        config = tmp_path / "config.toml"
        enable = True
        start = True
        uninstall = False

    with patch.dict(os.environ, {"HOME": str(home)}):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            rc = _cmd_install_systemd(_NS())
    assert rc == 0
    calls = [str(c.args[0]) for c in mock_run.call_args_list]
    assert any("enable" in s for s in calls)
    assert any("start" in s for s in calls)


def test_install_systemd_uninstall_removes_unit(tmp_path: Path) -> None:
    from lares.kmail.cli import _cmd_install_systemd
    home = tmp_path / "home"
    unit_dir = _systemd_unit_dir(home)
    unit_dir.mkdir(parents=True)
    (unit_dir / "lares-kmail.service").write_text("stub")

    class _NS:
        config = tmp_path / "config.toml"
        enable = False
        start = False
        uninstall = True

    with patch.dict(os.environ, {"HOME": str(home)}):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            rc = _cmd_install_systemd(_NS())
    assert rc == 0
    assert not (unit_dir / "lares-kmail.service").exists()
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_cli.py -v -k systemd`

Expected: ImportError / AttributeError for `_cmd_install_systemd`.

- [ ] **Step 3: Implement**

Add to `cli.py`:

```python
import subprocess


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
```

Wire into `build_parser`:

```python
    install_sd = install_sub.add_parser("systemd",
        help="install / enable / start the systemd --user unit")
    install_sd.add_argument("--enable", action="store_true")
    install_sd.add_argument("--start", action="store_true")
    install_sd.add_argument("--uninstall", action="store_true",
                            help="stop, disable, and remove the unit")
    install_sd.set_defaults(func=_cmd_install_systemd)
```

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: all pass.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/cli.py tests/kmail/test_cli.py
git commit -m "feat(cli): add 'lares install systemd' install/uninstall/enable/start"
```

---

## Task 22 — `lares install --check`

**Files:**
- Modify: `src/lares/kmail/cli.py`
- Modify: `tests/kmail/test_cli.py`

**Why:** Spec §10. Composite pre-flight: helpers found in the package, config exists & valid, Akonadi server reachable on D-Bus, Ollama reachable + model pulled, systemd unit installed.

- [ ] **Step 1: Write the failing tests**

```python
def test_install_check_reports_all_pass(
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lares.kmail.cli import _cmd_install_check
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
        rc = _cmd_install_check(_NS())
    out = capsys.readouterr().out
    assert rc == 0
    assert "✓ ollama" in out.lower()
    assert "✓ config" in out.lower()
```

- [ ] **Step 2: Run; verify failure**

Run: `uv run pytest tests/kmail/test_cli.py -v -k install_check`

Expected: ImportError.

- [ ] **Step 3: Implement**

Add to `cli.py`:

```python
def _cmd_install_check(ns: argparse.Namespace) -> int:
    skip = set(os.environ.get("LARES_CHECK_SKIP", "").split(","))
    fails: list[str] = []
    passes: list[str] = []

    # 1. Helpers in package
    if "helpers" not in skip:
        for name in ("lares-akonadi-notify", "lares-akonadi-mutate"):
            helper = Path(str(resources.files("lares") / "_bin" / name))
            if helper.is_file() and os.access(helper, os.X_OK):
                passes.append(f"helper {name}")
            else:
                fails.append(
                    f"helper {name} missing or not executable at {helper}\n"
                    "  Fix:  uv sync   (rebuild C++ helpers)"
                )

    # 2. Config exists & valid
    cfg: LaresConfig | None = None
    try:
        cfg = _load(ns)
        passes.append("config valid")
    except FileNotFoundError:
        fails.append(
            f"config not found at {ns.config}\n"
            "  Fix:  lares install config"
        )
    except Exception as exc:  # noqa: BLE001 — boundary validation surfaces here
        fails.append(f"config invalid: {exc}")

    # 3. Ollama reachable + model pulled (only if config loaded)
    if cfg is not None:
        try:
            with httpx.Client(base_url=cfg.lares.ollama.endpoint, timeout=5.0) as client:
                r = client.get("/api/tags")
                r.raise_for_status()
                models = {m.get("name") for m in r.json().get("models", [])}
                if cfg.lares.ollama.model in models:
                    passes.append(f"ollama model {cfg.lares.ollama.model} pulled")
                else:
                    fails.append(
                        f'ollama model "{cfg.lares.ollama.model}" not pulled\n'
                        f"  Fix:  ollama pull {cfg.lares.ollama.model}"
                    )
        except httpx.HTTPError as exc:
            fails.append(
                f"ollama not reachable at {cfg.lares.ollama.endpoint}: {exc}\n"
                "  Fix:  start the ollama service (systemctl --user start ollama)"
            )

    # 4. Akonadi reachable (best-effort dbus probe)
    if "akonadi" not in skip:
        r = subprocess.run(
            ["qdbus6", "org.freedesktop.Akonadi"],
            check=False, capture_output=True,
        )
        if r.returncode == 0:
            passes.append("akonadi reachable")
        else:
            fails.append(
                "akonadi not reachable on D-Bus\n"
                "  Fix:  akonadictl start"
            )

    # 5. systemd unit installed
    if "systemd" not in skip:
        unit = _user_unit_dir() / "lares-kmail.service"
        if unit.is_file():
            passes.append(f"systemd unit at {unit}")
        else:
            fails.append(
                "systemd unit not installed\n"
                "  Fix:  lares install systemd"
            )

    for p in passes:
        sys.stdout.write(f"✓ {p}\n")
    for f in fails:
        sys.stdout.write(f"✗ {f}\n")
    return 1 if fails else 0
```

Wire into `build_parser`:

```python
    install_check = install_sub.add_parser("check",
        help="composite preflight: helpers, config, ollama, akonadi, systemd")
    install_check.set_defaults(func=_cmd_install_check)
```

Note: the user calls this as `lares install check`, not `lares install --check` (argparse-friendly). The spec's `--check` syntax is reframed as a subcommand to keep the argparse tree consistent.

- [ ] **Step 4: Run; verify pass**

Run: `uv run pytest tests/kmail/test_cli.py -v`

Expected: all pass.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not integration"
git add src/lares/kmail/cli.py tests/kmail/test_cli.py
git commit -m "feat(cli): add 'lares install check' composite preflight"
```

---

## Task 23 — Integration tests

**Files:**
- Create: `tests/kmail/test_helpers_integration.py`
- Create: `tests/kmail/test_ollama_integration.py`

**Why:** Spec §12. Marked `@pytest.mark.integration`; CI runs them via `workflow_dispatch` / nightly only.

For v0.1, both suites are deliberately small. They establish the harness; the regression set grows organically.

- [ ] **Step 1: Create `tests/kmail/test_helpers_integration.py`**

```python
# SPDX-License-Identifier: MIT
"""Integration tests for the C++ helpers against a real (sandboxed) Akonadi.

These tests require a running Akonadi server with the maildir resource
configured against a test directory. Run manually:

    pytest -m integration tests/kmail/test_helpers_integration.py

Skipped automatically if `qdbus6 org.freedesktop.Akonadi` reports
unreachable.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from lares.kmail.mutate import Mutate


def _akonadi_up() -> bool:
    r = subprocess.run(
        ["qdbus6", "org.freedesktop.Akonadi"],
        check=False, capture_output=True,
    )
    return r.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _akonadi_up(), reason="akonadi not running"),
]


@pytest.mark.asyncio
async def test_mutate_helper_starts_and_responds_to_fetch_unknown() -> None:
    """Smoke test: helper binary launches, accepts JSON on stdin, returns error
    for an unknown item_id. Validates the wire protocol end-to-end."""
    from importlib import resources
    from pathlib import Path
    helper = Path(str(resources.files("lares") / "_bin" / "lares-akonadi-mutate"))
    if not helper.exists():
        pytest.skip("mutate helper not built")
    async with Mutate.from_command([str(helper), "--max-body-bytes", "1024"]) as m:
        from lares.kmail.mutate import MutateError
        with pytest.raises(MutateError) as ei:
            await m.fetch(99999999)
        assert ei.value.code == "not_found"
```

- [ ] **Step 2: Create `tests/kmail/test_ollama_integration.py`**

```python
# SPDX-License-Identifier: MIT
"""Integration tests for the classifier against a real local Ollama.

Run manually with:

    OLLAMA_TEST_MODEL=qwen3:1.7b-instruct-2507 \
    pytest -m integration tests/kmail/test_ollama_integration.py
"""

from __future__ import annotations

import email
import os
from email.message import Message
from pathlib import Path

import pytest

from lares.kmail.classifier import Classifier, FetchedItem
from lares.kmail.config import KMailConfig, LaresConfig, LaresShared, OllamaConfig


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif("OLLAMA_TEST_MODEL" not in os.environ, reason="OLLAMA_TEST_MODEL unset"),
]


_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> Message:
    return email.message_from_bytes((_FIXTURES_DIR / name).read_bytes())


def _to_fetched(msg: Message, item_id: int = 1) -> FetchedItem:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                break
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
    return FetchedItem(
        item_id=item_id,
        headers={
            "From": msg.get("From", ""),
            "To": msg.get("To", ""),
            "Subject": msg.get("Subject", ""),
            "List-Id": msg.get("List-Id", ""),
            "Date": msg.get("Date", ""),
        },
        body_text=body,
    )


def _cfg() -> LaresConfig:
    return LaresConfig(
        lares=LaresShared(
            log_level="INFO",
            ollama=OllamaConfig(model=os.environ["OLLAMA_TEST_MODEL"]),
        ),
        kmail=KMailConfig(
            tags={
                "personal": "A real human writing to me directly.",
                "business": "Business inquiry / contract / invoice.",
                "newsletter": "Marketing email or digest.",
                "notification": "Transactional / automated mail.",
            },
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture", "expected_category"),
    [
        ("personal.eml", "personal"),
        ("business.eml", "business"),
        ("newsletter.eml", "newsletter"),
        ("notification.eml", "notification"),
    ],
)
async def test_classifier_assigns_expected_category(
    fixture: str, expected_category: str,
) -> None:
    cfg = _cfg()
    async with Classifier(cfg) as c:
        verdict = await c.classify(_to_fetched(_load(fixture)))
    assert verdict.raw_category == expected_category, (
        f"expected {expected_category} for {fixture}, got "
        f"{verdict.raw_category} ({verdict.confidence:.2f})"
    )
    assert verdict.confidence >= 0.5
```

- [ ] **Step 3: Verify the unit suite still passes and integration tests are NOT auto-run**

Run: `uv run pytest -v`

Expected: integration tests are collected but **deselected** (because the marker filter is `-m "not integration"` by default? actually pytest collects them but they only skip when their marker condition is met OR when filtered). Run `uv run pytest -m "not integration" -v` to be explicit.

Expected: integration tests not run; unit suite (42+ tests) all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/kmail/test_helpers_integration.py tests/kmail/test_ollama_integration.py
git commit -m "test(kmail): add integration smoke tests for helpers and classifier"
```

---

## Task 24 — README update

**Files:**
- Modify: `README.md`

**Why:** Spec §14. Document install, model selection, troubleshooting.

- [ ] **Step 1: Replace `README.md` content**

Existing content keeps the top-level "What Lares is" framing. Add an "Install" section, a "Configuration" section, and a "Troubleshooting" section. Full new content:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for v0.1 install, config, and troubleshooting"
```

---

## Task 25 — Update CLAUDE.md to reflect new structure

**Files:**
- Modify: `CLAUDE.md`

**Why:** Spec §14. Note that `src/akonadi_bridge/` now exists and the build backend is `scikit-build-core`.

- [ ] **Step 1: Find the "What this repo is" section in `CLAUDE.md`** and add to the module layout list:

Find:
```markdown
- `lares.kmail` — Akonadi triage agent (`systemd --user` service, D-Bus to Akonadi).
```

Replace surrounding paragraph with:

```markdown
- `lares.kmail` — Akonadi triage agent (`systemd --user` service). Talks to Akonadi via two small C++/Qt6 helper binaries (`lares-akonadi-notify`, `lares-akonadi-mutate`) shipped inside the wheel — see `docs/superpowers/specs/2026-05-18-kmail-triage-agent-design.md` for the rationale (no Python binding to Akonadi exists; D-Bus alone can't carry the notification stream or apply tags). Python owns all policy.
- `src/akonadi_bridge/` — the two C++ helpers (source-only; built and installed into `src/lares/_bin/` by `scikit-build-core`).
- `lares.krunner` — KRunner LLM action (planned).
- `lares.core` — shared Ollama client, config loader, logging (deferred until a second agent exists; root §2 of the overlord).
- `lares.cli` — `lares` CLI for inspection, agent control, debugging (currently lives at `lares.kmail.cli`; promoted when the second agent lands).
```

- [ ] **Step 2: Find the "Stack" / dependencies area** and add a one-liner noting the build backend swap. Find the line beginning `**Python 3.12+, \`uv\` for deps, ...**` and append:

```markdown
- Build backend is **`scikit-build-core`** (PEP 517), not `hatchling`. The wheel ships both Python and the C++ bridge helpers; CMake config lives at the repo root and under `src/akonadi_bridge/`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): note akonadi_bridge layout and scikit-build-core backend"
```

---

## Self-review checklist

After all tasks land, sanity-check against the spec:

- [ ] §1 Purpose — implemented (full flow operational).
- [ ] §2 In-scope items 1–11 — all covered. Out-of-scope items remain out-of-scope.
- [ ] §3 Architecture — diagram matches code; two C++ helpers + one Python service.
- [ ] §4 Build & packaging — scikit-build-core (Task 1), CMakeLists (Task 2), CI deps (Task 3), wheel layout (Task 12/13).
- [ ] §5 Helper contracts — notify NDJSON (Task 12), mutate JSON I/O (Task 13).
- [ ] §6 Service — modules in Tasks 4–10. **Startup catchup was deferred to v0.2 via Task 17 spec amendment.**
- [ ] §7 Configuration — Task 5 + skeleton Task 18.
- [ ] §8 State storage — Task 6.
- [ ] §9 Classifier — Task 7.
- [ ] §10 CLI surface — Tasks 14–22. `backfill` / `catchup` stubbed per amended spec.
- [ ] §11 systemd & install — Tasks 20–22.
- [ ] §12 Testing — unit Tasks 4–10/14–22, integration Task 23.
- [ ] §13 Risks — risks 1–5 acknowledged in code/docs; risk 6 added by Task 17.
- [ ] §14 Docs — README (Task 24), CLAUDE.md (Task 25), spec (already committed).
- [ ] §15 Decisions journal — append by Task 17 only.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-kmail-triage-agent-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with clean context per task. Best fit here because the plan has 24 distinct tasks and many touch overlapping files (notably `cli.py`, which grows across Tasks 14–22).

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review. Faster cycle time per task but main-thread context fills up quickly with 24 tasks.

Which approach?
