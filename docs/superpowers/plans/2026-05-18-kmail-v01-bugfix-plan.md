# `lares.kmail` v0.1 bug-fix pass — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two v0.1-blocking bugs uncovered by the 2026-05-18 desktop smoke test: a stdin-reader bug in `lares-akonadi-mutate` that kills the helper after one async op, and a missing state directory on first systemd boot.

**Architecture:** Two commits straight to `main`. Commit 1 replaces the helper's `std::cin`/`getline` stdin reader with a non-blocking `::read()` + `QByteArray` line accumulator; ships a new pytest that drives the real binary with three sequential ops. Commit 2 swaps `ReadWritePaths=` for `StateDirectory=lares` in the systemd unit; amends the existing install-systemd test.

**Tech Stack:** C++ (Qt 6 / KPim6 / KMime), Python 3.12+ (asyncio, pytest, pytest-asyncio), scikit-build-core wheel build, systemd `--user` units.

**Spec:** `docs/superpowers/specs/2026-05-18-kmail-v01-bugfix-design.md` (`484f01a`).

**Operating rule (from the v0.1 plan, still in effect):** Substantive code tasks get a full spec-review subagent after implementer. Quality gates between commits: `ruff check`, `ruff format --check`, `pyright --strict`, `pytest -m "not integration"`.

---

## File structure

| Path | Action | Purpose |
|---|---|---|
| `src/akonadi_bridge/mutate.cpp` | modify (lines 35-37, 273-303) | Replace stdin reader; add 4 new includes |
| `tests/kmail/test_mutate_helper_io.py` | create | Regression test for Bug B; drives real helper with 3 sequential ops |
| `packaging/systemd/lares-kmail.service` | modify (1 line) | Swap `ReadWritePaths=%h/.local/state/lares` → `StateDirectory=lares` |
| `tests/kmail/test_cli.py` | modify (in `test_install_systemd_writes_unit_to_user_dir`, around line 277) | Add two assertions on the rendered unit text |

No other files. No `service.py`, `mutate.py`, or `cli.py` changes — the Python contracts are correct; the regressions live entirely in the C++ helper and the unit file.

---

## Task 1: Bug B — mutate helper stdin reader rewrite

**Files:**
- Create: `tests/kmail/test_mutate_helper_io.py`
- Modify: `src/akonadi_bridge/mutate.cpp:35-37` (add 4 includes) and `:273-303` (replace stdin reader inside `main`)
- Test: `tests/kmail/test_mutate_helper_io.py`

The TDD discipline here is: write the test, install the *current* (buggy) helper, point the test at it via `LARES_HELPER_PATH`, observe the failure. Then rewrite the C++ reader, rebuild + reinstall the wheel, point the test at the *new* helper, observe pass.

- [ ] **Step 1: Write the failing test**

Create `tests/kmail/test_mutate_helper_io.py` with this exact content:

```python
# SPDX-License-Identifier: MIT
"""Regression test for the mutate helper's stdin reader (Bug B).

Drives the real `lares-akonadi-mutate` binary with three sequential `fetch`
ops over a single subprocess and asserts three responses come back. The
historical bug exited the helper after the first async op; the second op
raised `MutateError("mutate helper closed stdout", "internal")`.

Skips cleanly when:
- The helper binary is not materialised (editable installs via `uv sync`
  do not run CMake's install step; the canonical workaround is
  `uv tool install --reinstall .` plus pointing `LARES_HELPER_PATH` at
  the installed binary).
- Akonadi is not reachable. The bug only manifests when the helper's
  fetch path is genuinely async (ItemFetchJob queued on the event loop).
  Without a running Akonadi server, `handleFetch` early-returns
  synchronously via `ensureAkonadiOnline`, and the spurious-notifier
  fire we are guarding against does not occur. The test is therefore
  most useful on a developer machine with Akonadi running, and skips
  in container CI by design.
"""

from __future__ import annotations

import os
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from lares.kmail.mutate import Mutate, MutateError


def _helper_path() -> Path | None:
    env = os.environ.get("LARES_HELPER_PATH")
    if env:
        candidate = Path(env)
        return candidate if candidate.is_file() else None
    candidate = Path(str(resources.files("lares") / "_bin" / "lares-akonadi-mutate"))
    return candidate if candidate.is_file() else None


def _akonadi_up() -> bool:
    try:
        result = subprocess.run(
            ["qdbus6", "org.freedesktop.Akonadi"],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


@pytest.mark.asyncio
async def test_helper_handles_three_sequential_fetches() -> None:
    helper = _helper_path()
    if helper is None:
        pytest.skip(
            "mutate helper not built — set LARES_HELPER_PATH or run from a wheel install"
        )
    if not _akonadi_up():
        pytest.skip("akonadi not running — bug only reproduces on the async fetch path")

    async with Mutate.from_command([str(helper), "--max-body-bytes", "1024"]) as m:
        for n in range(3):
            with pytest.raises(MutateError) as exc_info:
                await m.fetch(999_999_999)
            err = exc_info.value
            assert "closed stdout" not in str(err), (
                f"helper exited after op {n + 1}: {err}"
            )
            assert err.code == "not_found", (
                f"unexpected error code on op {n + 1}: {err.code} — full message: {err}"
            )
```

- [ ] **Step 2: Run the test against the currently-installed (buggy) helper and verify it fails**

```bash
# The wheel was installed earlier in the session; point the test at that binary.
export LARES_HELPER_PATH=~/.local/share/uv/tools/lares/lib/python3.14/site-packages/lares/_bin/lares-akonadi-mutate
uv run pytest tests/kmail/test_mutate_helper_io.py -v
```

Expected: FAIL on op 2 with `helper exited after op 2: mutate helper closed stdout`.

If the test instead `SKIPPED` with "akonadi not running", start KMail at least once to bring Akonadi up (Akonadi starts on demand) and re-run.

If the test instead `SKIPPED` with "mutate helper not built", run `uv tool install --reinstall .` and recompute the `LARES_HELPER_PATH` (the Python minor version in the path may have changed).

- [ ] **Step 3: Edit `src/akonadi_bridge/mutate.cpp` — add new includes**

Find the `#include <iostream>` line near line 35-36. Replace this block:

```cpp
#include <iostream>
#include <memory>
```

with:

```cpp
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <memory>
#include <unistd.h>
```

- [ ] **Step 4: Edit `src/akonadi_bridge/mutate.cpp` — add the line buffer to the anonymous namespace**

Find this section (around line 38-43):

```cpp
namespace
{

constexpr const char *LARES_PREFIX = "lares-";

int g_maxBodyBytes = 8192;
```

Add one new line after `int g_maxBodyBytes = 8192;`:

```cpp
namespace
{

constexpr const char *LARES_PREFIX = "lares-";

int g_maxBodyBytes = 8192;
QByteArray g_inbuf; // line accumulator across notifier fires
```

- [ ] **Step 5: Edit `src/akonadi_bridge/mutate.cpp` — replace the stdin reader inside `main`**

Find this exact block at the end of `main()` (around lines 290-301), immediately after the `g_maxBodyBytes` parser handling and before `return app.exec();`:

```cpp
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
```

Replace with:

```cpp
    // Read stdin via non-blocking ::read() on STDIN_FILENO; accumulate into
    // g_inbuf and dispatch each whole line. Quitting only on a real EOF
    // (::read returns 0) — never on a spurious notifier fire — fixes the
    // historical bug where buffered std::cin + QSocketNotifier interactions
    // exited the helper after one async op.
    const int stdinFlags = fcntl(STDIN_FILENO, F_GETFL);
    if (stdinFlags < 0 || fcntl(STDIN_FILENO, F_SETFL, stdinFlags | O_NONBLOCK) < 0) {
        std::cerr << "lares-akonadi-mutate: cannot set stdin non-blocking: "
                  << std::strerror(errno) << '\n';
        return 1;
    }

    auto *notifier = new QSocketNotifier(STDIN_FILENO, QSocketNotifier::Read, &app);
    QObject::connect(notifier, &QSocketNotifier::activated,
        [notifier](QSocketDescriptor) {
            for (;;) {
                char chunk[4096];
                const ssize_t n = ::read(STDIN_FILENO, chunk, sizeof(chunk));
                if (n > 0) {
                    g_inbuf.append(chunk, static_cast<int>(n));
                    for (int nl; (nl = g_inbuf.indexOf('\n')) >= 0; ) {
                        dispatch(g_inbuf.left(nl));
                        g_inbuf.remove(0, nl + 1);
                    }
                    continue;
                }
                if (n == 0) {
                    notifier->setEnabled(false);
                    QCoreApplication::quit();
                    return;
                }
                if (errno == EINTR) continue;
                if (errno == EAGAIN || errno == EWOULDBLOCK) return;
                std::cerr << "lares-akonadi-mutate: read(stdin) failed: "
                          << std::strerror(errno) << '\n';
                notifier->setEnabled(false);
                QCoreApplication::exit(1);
                return;
            }
        });

    return app.exec();
```

The `std::cin` / `std::getline` reference is now gone from the reader; `#include <iostream>` stays because `writeResponse`/`writeError` use `std::cout` and `std::cerr`. The unused inclusion does not cost anything and removing it is out of scope.

- [ ] **Step 6: Rebuild + reinstall the wheel**

```bash
uv tool install --reinstall .
```

Expected: build runs (CMake + ninja), wheel is produced, `lares` is reinstalled. The new helper lands at `~/.local/share/uv/tools/lares/lib/python<X.Y>/site-packages/lares/_bin/lares-akonadi-mutate`.

If the Python minor version on this host has changed since the test was written, recompute `LARES_HELPER_PATH`:

```bash
export LARES_HELPER_PATH=$(find ~/.local/share/uv/tools/lares/lib -name lares-akonadi-mutate -type f | head -1)
echo "$LARES_HELPER_PATH"
```

- [ ] **Step 7: Run the regression test and verify it passes**

```bash
uv run pytest tests/kmail/test_mutate_helper_io.py -v
```

Expected: 1 passed (or 1 skipped with the documented reason — if it skips here you need to fix the skip condition before continuing, since the whole point is to validate the fix).

- [ ] **Step 8: Run the full quality gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
```

Expected: all four green. The wider pytest run will SKIP the new regression test (the editable-install `.venv` doesn't have the helper materialised and `LARES_HELPER_PATH` is only set in your current shell); that's correct.

- [ ] **Step 9: Manual desktop smoke — drive a real classification through `retag`**

Pick a recent inbox item-id. The Akonadi DB has a Unix socket at `~/.local/share/akonadi/socket-<hostname>-default/mysql.socket` and the DB user `dertechie` has access on this host (from the smoke session):

```bash
SOCK=$(ls ~/.local/share/akonadi/socket-*/mysql.socket 2>/dev/null | head -1)
mariadb -S "$SOCK" -u dertechie akonadi -B -N -e "
SELECT p.id FROM PimItemTable p
JOIN CollectionAttributeTable ca ON ca.collectionId=p.collectionId
WHERE ca.type='SpecialCollectionAttribute' AND ca.value='inbox'
ORDER BY p.id DESC LIMIT 1;
"
```

Then retag it:

```bash
ITEM_ID=$(mariadb -S "$SOCK" -u dertechie akonadi -B -N -e "
SELECT p.id FROM PimItemTable p
JOIN CollectionAttributeTable ca ON ca.collectionId=p.collectionId
WHERE ca.type='SpecialCollectionAttribute' AND ca.value='inbox'
ORDER BY p.id DESC LIMIT 1;
")
echo "retagging item $ITEM_ID"
lares kmail retag "$ITEM_ID"
lares kmail status
```

Expected: `lares kmail retag` completes without traceback; `lares kmail status` shows `last seen item id: <ITEM_ID>` and `queue depth: 0`. Confirm in KMail's tag UI (or via the DB) that the item gained one of `lares-personal | lares-business | lares-newsletter | lares-notification | lares-unclassified`. Record the observed verdict tag for use in the commit message body.

If `retag` still raises `MutateError("mutate helper closed stdout", ...)`, **do not commit** — the rewrite is incomplete. Re-read the change against §4 of the spec and re-iterate from Step 3.

- [ ] **Step 10: Commit**

```bash
git add src/akonadi_bridge/mutate.cpp tests/kmail/test_mutate_helper_io.py
git commit -m "$(cat <<'EOF'
fix(bridge): mutate helper drains stdin via raw read(), not std::cin

The previous reader used QSocketNotifier(fileno(stdin), Read) plus
std::getline(std::cin, …). After one async op the helper voluntarily
called QCoreApplication::quit(): a spurious notifier::activated fire
hit std::getline against an empty stream, getline set eofbit and
returned false, and the EOF branch ran even though Python's end of
the pipe was still open. This killed every flow that issued more than
one mutate op over the same subprocess — most importantly the live
service's fetch → set_tags(pending) → set_tags(verdict) chain and the
two-call `lares kmail retag` path.

Replace std::cin with a non-blocking ::read(STDIN_FILENO, …) loop and
a module-level QByteArray line accumulator. Quit only on real EOF
(read returns 0); treat EAGAIN/EWOULDBLOCK as "no more data, wait".
The protocol contract documented in mutate.cpp:4-13 is unchanged.

Adds tests/kmail/test_mutate_helper_io.py: drives the real helper
with three sequential fetch ops and asserts three responses come back
correlated by id. Skips cleanly when the helper binary is not
materialised (editable installs) or Akonadi is not running (bug only
reproduces on the async fetch path).

Closes Bug B in docs/superpowers/specs/2026-05-18-kmail-v01-bugfix-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Bug A — `StateDirectory=lares` in systemd unit

**Files:**
- Modify: `packaging/systemd/lares-kmail.service` (one-line swap)
- Modify: `tests/kmail/test_cli.py` (add two assertions inside `test_install_systemd_writes_unit_to_user_dir`)
- Test: `tests/kmail/test_cli.py::test_install_systemd_writes_unit_to_user_dir`

- [ ] **Step 1: Write the failing test assertions**

Open `tests/kmail/test_cli.py`. Find `test_install_systemd_writes_unit_to_user_dir` (starts at line 261). The body currently ends with this block (around line 274-279):

```python
    assert rc == 0
    unit = unit_dir / "lares-kmail.service"
    assert unit.exists()
    assert "Description=Lares" in unit.read_text()
    # daemon-reload always
    assert any("daemon-reload" in str(c.args) for c in mock_run.call_args_list)
```

Replace with:

```python
    assert rc == 0
    unit = unit_dir / "lares-kmail.service"
    assert unit.exists()
    unit_text = unit.read_text()
    assert "Description=Lares" in unit_text
    # Bug A regression — first boot must not fail on a missing state dir.
    assert "StateDirectory=lares" in unit_text
    assert "ReadWritePaths=" not in unit_text
    # daemon-reload always
    assert any("daemon-reload" in str(c.args) for c in mock_run.call_args_list)
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
uv run pytest tests/kmail/test_cli.py::test_install_systemd_writes_unit_to_user_dir -v
```

Expected: FAIL on `assert "StateDirectory=lares" in unit_text` — the current unit file ships `ReadWritePaths=%h/.local/state/lares` and no `StateDirectory=` line.

- [ ] **Step 3: Edit the unit file**

Open `packaging/systemd/lares-kmail.service`. It currently reads:

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

Change exactly one line — replace:

```ini
ReadWritePaths=%h/.local/state/lares
```

with:

```ini
StateDirectory=lares
```

Final file:

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
StateDirectory=lares
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

Note: do **not** also delete `ProtectSystem=strict`. `StateDirectory=` cooperates with `ProtectSystem=strict` by implicitly adding `$XDG_STATE_HOME/lares` to the writable set.

- [ ] **Step 4: Run the test and verify it passes**

```bash
uv run pytest tests/kmail/test_cli.py::test_install_systemd_writes_unit_to_user_dir -v
```

Expected: 1 passed. (The session-scoped autouse fixture in `tests/kmail/conftest.py` copies the updated source unit into `src/lares/_systemd/` before the test reads it.)

- [ ] **Step 5: Run the full quality gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
```

Expected: all four green.

- [ ] **Step 6: Manual smoke — clean install on a fresh state dir**

Tear down the current install and start over to prove first boot succeeds without manual `mkdir`:

```bash
systemctl --user stop lares-kmail
systemctl --user disable lares-kmail
rm -rf ~/.local/state/lares
ls ~/.local/state/lares 2>&1 | head -1   # No such file or directory

uv tool install --reinstall .             # rebuild + reinstall (picks up the new unit)
lares install systemd --enable --start
sleep 2
systemctl --user is-active lares-kmail    # expected: active
ls -ld ~/.local/state/lares               # expected: drwx------ owned by $USER
journalctl --user -u lares-kmail --since "1 minute ago" --no-pager | grep -c "NAMESPACE"
# expected: 0  (the failure mode is gone)
```

If `is-active` is not `active`, `journalctl --user -u lares-kmail -e --no-pager` will tell you why — investigate before continuing.

- [ ] **Step 7: Commit**

```bash
git add packaging/systemd/lares-kmail.service tests/kmail/test_cli.py
git commit -m "$(cat <<'EOF'
fix(packaging): use StateDirectory= so first boot doesn't fail on missing dir

The unit shipped ProtectSystem=strict plus
ReadWritePaths=%h/.local/state/lares. systemd requires
ReadWritePaths= targets to exist before launch, so on a fresh install
the service flapped with status=226/NAMESPACE and "Failed to set up
mount namespacing: …/.local/state/lares: No such file or directory"
until something — usually the user — created the directory by hand.

Replace ReadWritePaths= with StateDirectory=lares. systemd creates
$XDG_STATE_HOME/lares with mode 0700 on unit start and implicitly
adds it to the writable set, so ProtectSystem=strict keeps the rest
of the FS read-only and the default state_db_path
(~/.local/state/lares/kmail.db) still resolves correctly. Same
behaviour, no manual prep step on first install.

Amends tests/kmail/test_cli.py::test_install_systemd_writes_unit_to_user_dir
with two new assertions on the rendered unit text:
"StateDirectory=lares" present, "ReadWritePaths=" absent.

Closes Bug A in docs/superpowers/specs/2026-05-18-kmail-v01-bugfix-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Post-task wrap

After both commits land:

- [ ] Run `git log --oneline origin/main..HEAD | head -5` and confirm two new commits sit on top of `484f01a` (the spec commit). 38 commits ahead of `origin/main`.
- [ ] Update memory: in `~/.claude/projects/-home-dertechie-Repositories-github-com-DerTechie-lares-agents/memory/project_kmail_v01_resume.md`, the "v0.1 smoke-test findings (2026-05-18)" section's two open bugs are now fixed; either annotate them as closed (with the commit SHAs) or move them into a "v0.1 smoke-test fixes" subsection alongside "what's next".
- [ ] Update `MEMORY.md` index — its current one-liner mentions "2 bugs blocking v0.1" past tense ("uncovered"), which is still accurate. Optionally extend to "uncovered + fixed in <SHA1>, <SHA2>".
- [ ] Do **not** push `origin/main` or tag `v0.1.0` from this plan. Both are explicit out-of-scope items in the spec (§2); they need a separate go-ahead from the user.

The plan is done at that point. The v0.1 release candidate is the new HEAD.

---

## Self-review

**Spec coverage check** — walking the spec's sections against the plan:

| Spec section | Plan task / step |
|---|---|
| §3 Bug A symptom & root cause | Task 2 Step 3 narrative + commit body |
| §3 Bug A fix (`StateDirectory=lares`) | Task 2 Step 3 |
| §3 Files touched (unit + test_cli.py) | Task 2 Steps 1, 3 |
| §4 Bug B symptom & root cause | Task 1 Step 1 (test docstring) + commit body |
| §4 Bug B fix (raw `::read`, line accumulator, EOF on `read==0`) | Task 1 Steps 3–5 |
| §4 Files touched (mutate.cpp + new test) | Task 1 Steps 1, 3, 4, 5 |
| §4 Behavioral contract preserved | Task 1 Step 5 narrative; commit body |
| §5.1 Bug B test (real binary, 3 sequential ops) | Task 1 Step 1 |
| §5.2 Bug A test (two new assertions in existing test) | Task 2 Step 1 |
| §5.3 Manual desktop smoke between commits | Task 1 Step 9 (after Bug B, before Bug B commit) and Task 2 Step 6 (after Bug A, before Bug A commit) |
| §5.4 Quality gates each commit | Task 1 Step 8, Task 2 Step 5 |
| §6 Commit plan (two commits, exact messages) | Task 1 Step 10, Task 2 Step 7 |
| §7 Risks | Covered by the test design (skip-when-Akonadi-down docstring) and by Task 1 Step 9's failure clause |

All covered.

**Placeholder scan:** searched for "TBD", "TODO", "FIXME", "fill in", "..." — none in this plan's body. The four ellipses inside Python f-strings/docstrings are content, not placeholders.

**Type / signature consistency:** `Mutate.from_command(list[str])` matches the existing signature in `src/lares/kmail/mutate.py:70-71` (verified during context exploration). `MutateError.code` is the existing attribute set by `_call` in `mutate.py:138-139`. `resources.files("lares") / "_bin" / "lares-akonadi-mutate"` matches the existing pattern in `tests/kmail/test_helpers_integration.py`.

Plan is internally consistent and covers the spec.
