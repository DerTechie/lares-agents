# `lares.kmail` v0.1 — bug-fix pass — design spec

**Status:** implemented (`ecf4f3f`, `0f60e6d`); see "Implementation amendment" at the end of §4 for the Qt6 finding
**Date:** 2026-05-18
**Author:** Mike Esser
**Repo:** `DerTechie/lares-agents`
**Supersedes:** none; **amends:** [`2026-05-18-kmail-triage-agent-design.md`](2026-05-18-kmail-triage-agent-design.md) §5 (mutate helper I/O loop) and §10 (systemd unit)

## 1. Purpose

The kmail triage agent's v0.1 implementation is complete on `main` (HEAD `4cb1167`, 35 commits ahead of `origin/main`, never pushed). A desktop smoke test on 2026-05-18 against a real Arch + Plasma 6 box (Python 3.14.5, KMime 24.12, qwen3:4b model) uncovered two reproducible bugs that block a clean v0.1 release. This spec captures the fixes.

The two bugs were not caught by unit or integration tests because:
- **Bug A** requires a real `systemd --user` launch on a host where `$XDG_STATE_HOME/lares` doesn't already exist — test fixtures pre-create the state dir.
- **Bug B** requires driving the helper binary with two or more sequential ops over the same long-lived subprocess — existing tests use one-shot subprocesses or mock the helper.

## 2. Scope

### In scope

- Rewrite `lares-akonadi-mutate`'s stdin reader so the helper survives sequential ops over a persistent stdin pipe.
- Change `packaging/systemd/lares-kmail.service` so first boot doesn't fail on a missing `~/.local/state/lares`.
- One regression test per bug, both runnable under `pytest -m "not integration"`.

### Out of scope (explicit non-goals)

- `lares-akonadi-notify` rewrite — the helper does not read stdin, has no version of this bug. Confirmed by reading `src/akonadi_bridge/notify.cpp`.
- Helper protocol redesign — the existing protocol contract documented in `mutate.cpp:4-13` and in the v0.1 design spec §5 is correct as written; only its implementation is broken.
- Graceful-shutdown protocol op (`{"op":"quit"}`) — Python wrapper's `__aexit__` already terminates the subprocess via SIGTERM; that is sufficient.
- Pushing `origin/main`, tagging `v0.1.0`, publishing to PyPI — those come after this spec's commits land and after a manual re-run of the desktop smoke test passes.
- Any code change in `service.py`, `mutate.py` (Python wrapper), or `cli.py`. The Python contract is correct; the regressions live entirely in the C++ helper and the systemd unit.
- Changing the default `state_db_path` config value. `~/.local/state/lares/kmail.db` is what `StateDirectory=lares` produces; the two stay aligned.

## 3. Bug A — `lares install systemd` fails first boot on missing state dir

### Symptom

After `lares install systemd --enable --start`, the service flaps with `status=226/NAMESPACE` and the journal records:

```
(lares)[…]: lares-kmail.service: Failed to set up mount namespacing: /home/$USER/.local/state/lares: No such file or directory
(lares)[…]: lares-kmail.service: Failed at step NAMESPACE spawning /home/$USER/.local/bin/lares: No such file or directory
```

systemd retries with the default 5 s backoff and gives up after 5 attempts within the default `StartLimitBurst`.

### Root cause

`packaging/systemd/lares-kmail.service` declares:

```ini
ProtectSystem=strict
ReadWritePaths=%h/.local/state/lares
```

`ProtectSystem=strict` makes the entire filesystem read-only for the unit. `ReadWritePaths=` carves out a writable path — but systemd requires the path to exist before launch. On a fresh install, `~/.local/state/lares` does not exist yet (only `~/.local/state` may exist), so namespace setup fails and the process never starts.

### Fix

Replace `ReadWritePaths=%h/.local/state/lares` with `StateDirectory=lares`. systemd's `StateDirectory=` directive:

1. Auto-creates `$XDG_STATE_HOME/lares` (default `~/.local/state/lares`) at unit start with mode 0755.
2. Implicitly adds it to `ReadWritePaths=` so `ProtectSystem=strict` still applies elsewhere.
3. Exports `STATE_DIRECTORY=<absolute path>` as an env var — not used by lares today, but a free win.

`ProtectSystem=strict`, `NoNewPrivileges=true`, `Type=exec`, `Restart=on-failure`, `RestartSec=5`, `TimeoutStopSec=10`, `After=akonadi.service`, `PartOf=plasma-workspace.target`, `WantedBy=default.target` — all unchanged.

### Files touched

- `packaging/systemd/lares-kmail.service` — one-line swap.
- `tests/kmail/test_cli.py` — amend `test_install_systemd_writes_unit_to_user_dir` (line 261). The test already reads the rendered unit via `unit.read_text()` and asserts `"Description=Lares" in unit.read_text()`. Add two more assertions on the same text: `"StateDirectory=lares" in text` and `"ReadWritePaths=" not in text`.

## 4. Bug B — mutate helper exits after one async op

### Symptom

Driving `lares-akonadi-mutate` over a long-lived subprocess pipe with two sequential ops:

```python
await mutate.set_tags(1988, ["lares-pending"])   # returns response 1, OK
await mutate.fetch(1988)                          # MutateError: helper closed stdout
```

The helper exits with `returncode=0` between the two calls, before Python writes the second request. Reproducible from `lares kmail retag <id>` (which does this two-call sequence) and from any normal classification path through `service.py:consume_one_event` (which does `fetch` → `set_tags(pending)` → classify → `set_tags(verdict)`).

### Root cause

`src/akonadi_bridge/mutate.cpp:291-300`:

```cpp
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
```

Two layered problems:

1. **Buffered `std::cin` vs. fd-level poll.** `QSocketNotifier(Read)` is level-triggered on `STDIN_FILENO`. The first `getline` call drains the kernel pipe (one `read(0, …)` underneath libc) and parks any leftover bytes in `std::cin`'s streambuf. From systemd's perspective the fd is now "no data ready", so the notifier won't fire on those buffered bytes — a buffered op can sit unreachable. (In our reproducer this leftover-buffer case doesn't actually hit, but the design is fragile to it.)
2. **`getline` returns false on a spurious notifier fire.** Empirically observed: after `handleSetTags` finishes its async chain and writes its response, the notifier fires again before Python has written the second request. There is no new data on the fd; `getline` against an empty stream sets `failbit`/`eofbit` and returns false; the handler interprets this as EOF and calls `QCoreApplication::quit()`. The Qt event-loop bookkeeping that triggers the spurious fire is implementation-internal; we treat it as "any read of zero or `EAGAIN` is fine and not EOF". The contract of `read(2)` distinguishes them unambiguously; the `getline` API does not.

### Fix

Replace `std::cin` + `getline` with a non-blocking `::read(STDIN_FILENO, …)` loop inside the notifier callback, plus a `QByteArray` line accumulator. Quit only on real EOF (`read` returns 0).

```cpp
namespace {
QByteArray g_inbuf;   // line accumulator across notifier fires
}

// in main, after CLI parsing, before app.exec():

int flags = fcntl(STDIN_FILENO, F_GETFL);
if (flags < 0 || fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK) < 0) {
    // fatal — without O_NONBLOCK the read loop below would block.
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
                continue;  // try to drain more
            }
            if (n == 0) {                              // real EOF
                notifier->setEnabled(false);
                QCoreApplication::quit();
                return;
            }
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) return;  // wait for next fire
            // any other errno is unexpected — log and exit non-zero
            std::cerr << "lares-akonadi-mutate: read(stdin) failed: "
                      << std::strerror(errno) << '\n';
            notifier->setEnabled(false);
            QCoreApplication::exit(1);
            return;
        }
    });
```

New includes: `<unistd.h>` (`::read`, `STDIN_FILENO`), `<fcntl.h>` (`fcntl`, `O_NONBLOCK`), `<cerrno>` (`errno`), `<cstring>` (`std::strerror`).

### Implementation amendment (post-`ecf4f3f`)

The fix above is **necessary but not sufficient** on Qt 6.7+. With only the stdin-reader rewrite applied, the regression test still fails — the helper still exits after one async op. The deeper cause is `QCoreApplication::quitAutomatically()`: `Akonadi::ItemFetchJob` derives from `KJob`, which holds a `QEventLoopLocker` for the lifetime of the job. When the last locker is released (on `ItemFetchJob::result`), Qt 6 posts a `QEvent::Quit` and the event loop exits — independent of stdin state. This is a Qt 5 → Qt 6 semantic change.

The actual fix landed in `ecf4f3f` adds one line immediately after constructing `QCoreApplication`:

```cpp
QCoreApplication::setQuitLockEnabled(false);
```

This disables the quit-lock mechanism for the entire process. The helper's only exit paths become: `fcntl` bail-out (line 309), explicit `QCoreApplication::quit()` on stdin EOF (line 332), explicit `QCoreApplication::exit(1)` on unexpected `errno` from `::read` (line 340), and OS signals (default Qt handling). None of these paths rely on auto-quit, so disabling it is risk-free for this binary.

`lares-akonadi-notify` does not currently issue `KJob`s on its own (it only relays `Akonadi::Monitor` signals), but a future addition that constructed one would exhibit the same footgun. Track as a follow-up audit. **The same `setQuitLockEnabled(false)` pattern is the correct prophylaxis for any future Qt6-based CLI helper that drives KJobs.**

### Behavioral contract preserved

- **One JSON request per line in, one JSON response per line out** — unchanged. Lines without a trailing `\n` are held in `g_inbuf` until the newline arrives, exactly matching what `getline` was doing.
- **EOF behavior** — only real pipe close (`read` returns 0) quits the process. SIGTERM from the Python wrapper's `__aexit__` still works (Qt installs default signal handling that quits the event loop).
- **`--max-body-bytes` arg, `dispatch()`, `handleFetch`, `handleSetTags`, `applyTagsAndModify`, response framing** — all unchanged.
- **Concurrency** — `dispatch()` returns immediately (async Akonadi jobs are queued on the event loop); we do not need to serialize requests at the C++ level. The Python wrapper's `asyncio.Lock` already serializes at the application level.

### Files touched

- `src/akonadi_bridge/mutate.cpp` — replace the stdin reader; ~30 lines net change.
- `tests/kmail/test_mutate_helper_io.py` — new file; spawns the real helper binary and asserts N=3 sequential ops produce N=3 responses.

## 5. Test plan

### 5.1 Bug B regression test (new file)

`tests/kmail/test_mutate_helper_io.py`. Key properties:

- **Uses the real helper binary** from `lares._bin`. Path resolution via `importlib.resources.files("lares") / "_bin" / "lares-akonadi-mutate"`.
- **Skipped (not failed) when the binary is absent** — the project memory notes that editable installs via `uv sync` don't materialize wheel artifacts. Skip with a `pytest.skip(...)` if the path doesn't exist; CI's wheel build will exercise it.
- **No Akonadi required.** Bogus item-ids (e.g. `999_999_999`) are sent; the helper responds with `{"ok": false, "code": "akonadi_offline"}` if the test host lacks Akonadi, or `{"ok": false, "code": "not_found"}` if it has one. Either is fine — the regression signal is **count of responses**, not their content.
- **Drives N=3 ops over one subprocess.** The shape exercises the live-service path (`fetch` → `set_tags(pending)` → … → `set_tags(verdict)` is 3 ops). Each is correlated by `id` (e.g. `"r1"`, `"r2"`, `"r3"`); the test asserts each request id round-trips on the matching response.
- **Async test** via `pytest-asyncio` and the existing `asyncio_mode = "strict"` config.

Sketch:

```python
@pytest.mark.asyncio
async def test_helper_handles_sequential_ops_without_exiting():
    helper = importlib.resources.files("lares") / "_bin" / "lares-akonadi-mutate"
    if not Path(str(helper)).exists():
        pytest.skip("helper binary not built (editable install)")
    proc = await asyncio.create_subprocess_exec(
        str(helper), "--max-body-bytes", "8192",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async def roundtrip(req_id: str) -> dict:
            line = (json.dumps({"id": req_id, "op": "fetch", "item_id": 999_999_999}) + "\n").encode()
            proc.stdin.write(line)
            await proc.stdin.drain()
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
            assert raw, f"helper closed stdout before responding to {req_id}"
            return json.loads(raw)

        for rid in ("r1", "r2", "r3"):
            resp = await roundtrip(rid)
            assert resp["id"] == rid
            assert resp["ok"] is False  # bogus item_id; ok:false is correct
            assert resp["code"] in {"not_found", "akonadi_offline"}

        assert proc.returncode is None, "helper exited prematurely"
    finally:
        proc.terminate()
        await proc.wait()
```

### 5.2 Bug A regression test (amended test)

Existing test: `tests/kmail/test_cli.py::test_install_systemd_writes_unit_to_user_dir` (line 261). It already exercises the install path — patches `subprocess.run`, calls `_cmd_install_systemd`, reads the written unit file with `unit.read_text()`, asserts `"Description=Lares" in unit.read_text()`. Add two assertions on the same text:

```python
text = unit.read_text()
assert "Description=Lares" in text
assert "StateDirectory=lares" in text         # new: catches Bug A regression
assert "ReadWritePaths=" not in text           # new: catches Bug A regression
```

The session-scoped autouse fixture in `tests/kmail/conftest.py` (per project memory) that copies `packaging/systemd/lares-kmail.service` into `src/lares/_systemd/` for tests still applies — it copies whatever we ship, so changing the source unit file is enough.

### 5.3 Manual desktop smoke after Bug B commit, before Bug A commit

Re-run today's e2e (build wheel, `uv tool install --reinstall .`, `lares kmail retag 1988`) and confirm a green classification — i.e. one of the four taxonomy tags applied to the test item, not `lares-pending` or `lares-error`. Document the result in the commit message.

### 5.4 Quality gates

All four must be clean at each commit before pushing:

- `ruff check`
- `ruff format --check`
- `pyright --strict`
- `pytest -m "not integration"`

## 6. Commit plan

Two commits straight to `main`:

1. `fix(bridge): mutate helper drains stdin via raw read(), not std::cin`
   - `src/akonadi_bridge/mutate.cpp` (rewrite stdin reader + 4 new includes)
   - `tests/kmail/test_mutate_helper_io.py` (new)
   - Commit body cites this spec by path and explains the QSocketNotifier+stdio interaction.
2. `fix(packaging): use StateDirectory= so first boot doesn't fail on missing dir`
   - `packaging/systemd/lares-kmail.service` (one-line swap)
   - `tests/kmail/test_cli.py` (two new assertions in `test_install_systemd_writes_unit_to_user_dir`)

Between the two commits: rebuild the wheel, reinstall the tool, manually re-run `lares kmail retag` against a real inbox item, confirm a green tag in `kmail status` and in KMail's tag UI. Record the observed verdict tag in commit 2's body.

After commit 2: the v0.1 release candidate is complete. Pushing `origin/main` and tagging `v0.1.0` are out of scope for this spec — confirm with the user as a separate step.

## 7. Risks

- **`StateDirectory=` semantics differ on system units.** Not relevant here — the unit is `--user` only. The unit file's `[Install] WantedBy=default.target` and `PartOf=plasma-workspace.target` both stay; both are user-unit idioms.
- **The new mutate reader could in theory leave a half-line in `g_inbuf` forever on a misbehaving sender.** Acceptable: the Python wrapper always writes `(json + "\n").encode()`. A sender that never sends a newline would also have hung the old `getline`-based implementation.
- **Spurious notifier fires under load.** The new design is robust to them by construction (`EAGAIN` ≠ EOF).
- **Helper still exits on `SIGPIPE` if Python closes stdout.** Unchanged behavior; Python doesn't do this until `__aexit__` is on its way out.
- **The regression test relies on a built helper binary.** The skip-if-missing behavior is conservative — a CI matrix that omits the wheel build would skip the test and report green even if regressions returned. Mitigated by: the standard CI workflow already builds the wheel (see project memory; commit `b0d2eb4` + `a1b8540`).

## 8. Source of truth links

- Live state, what's done, what's blocking v0.1 release: `/home/dertechie/.claude/projects/-home-dertechie-Repositories-github-com-DerTechie-lares-agents/memory/project_kmail_v01_resume.md` § "v0.1 smoke-test findings (2026-05-18)".
- The v0.1 design spec being amended: `docs/superpowers/specs/2026-05-18-kmail-triage-agent-design.md`.
- Project CLAUDE.md rules: type-checking, error handling, async idioms, no `bare except`.
