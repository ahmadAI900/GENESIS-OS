# Fast gate tiering - mechanical classification of `live`-marked tests

Status: **COMPLETE through A5; B1 PARTIAL.** Classification is by recorded
evidence, cross-checked against an independent static signal, applied
through data rather than by editing test files, and enforced permanently
by a tripwire that catches unclassified tests written after the fact.

- Continuation A1-A3 (superseded, retained for history below)
- **A4** = "Continuation A4" section
- **A5** = "Continuation A5 - the tripwire"
- **B1** = "Continuation B1" (entry-point behaviour, tripwire, verify_all)

Status: **B1 PARTIAL.** The entry point now has fast-tier behavioural
coverage and the gate has a permanent tripwire, but one pre-existing
test is still flaky and one behavioural mutation is still missed. Both
are listed rather than papered over.

Date: 2026-10-11 (A4), 2026-10-12 (A5/B1)

## Why this exists

The fast gate (`-m "not live"`) missed real breakage three times in this
project. Every time, the cause was the same: `live` was a single bucket
holding both "opens a real browser and talks to the network" and
"constructs `GenesisOS` and asserts on a return value". The 22 tests broken
by the `GenesisOS` class-truncation regression were all in that bucket and
all invisible to the gate.

Classifying by reading tests is guesswork. This document classifies by
experiment.

---

# Continuation A4

## 1. The blind spot, named

A3's recorder wrapped `win32gui`, `pyautogui`, `selenium.webdriver` and
`playwright.sync_api` by looking them up in `sys.modules` at install
time. They were not there: the code under test imports all four
**lazily, inside functions**. So `_wrap_module()` silently wrapped
nothing, and six control tests recorded nothing.

That was the surface defect. It was not the whole defect. Two deeper
ones only became visible once the canaries were written:

### 1a. The product does not use `win32gui` for window work at all

`genesis_os/window_models.py` and `genesis_os/application_state_machine.py`
call `ctypes.windll.user32` **directly**. The A3 recorder wrapped
`win32gui` and would have missed every real GUI call in this codebase
even if its import timing had worked. Fixing only the timing bug would
have produced a recorder that looked healthy and still reported zero
GUI events.

There is no `ctypes.call_function` audit event in CPython 3.12
(verified: `sys.addaudithook` sees `ctypes.dlopen` and `ctypes.dlsym`,
nothing per-call). So the observation point is the DLL attribute lookup,
which every call in this codebase transits:

```python
ctypes.CDLL.__getattr__ = rec_getattr   # wraps, caches on the instance
```

### 1b. `importing pyautogui is itself a GUI action`

Measured, not assumed. A fresh interpreter that does nothing but
`import pyautogui` makes **~110 calls to `user32.VkKeyScanA`**, plus
`SetProcessDPIAware` and `GetDC`. pyautogui builds its keyboard map at
import time.

So a test whose only GUI contact is "the product imported pyautogui"
records **no `gui` event at all** under module-attribute wrapping. This
is the single strongest argument for the ctypes layer.

## 2. The recorder: three layers

`tools/record_probe.py`, opt-in, never loaded in a normal run.

| layer | mechanism | catches |
|---|---|---|
| 1 | `sys.addaudithook` | `subprocess.Popen`, `os.system`, `os.startfile`, `socket.connect`, `socket.getaddrinfo`, `ctypes.dlopen/dlsym` |
| 2 | `ctypes.CDLL.__getattr__` | every `user32`/`kernel32` call - **the real product path** |
| 3 | `sys.meta_path` loader wrapper + PEP 562 `__getattr__` wrapper | `win32gui`, `win32api`, `pyautogui`, `selenium.webdriver`, `playwright.sync_api`, wrapped **when the module finishes loading** |

Layer 1 is immune to import timing and stale references because CPython
raises the event at the call site. Layers 2 and 3 are not, which is why
layer 1 carries process/network and layers 2-3 carry the GUI work the
audit system cannot see.

### Two wrappers that had to be removed, and why

- **`subprocess.Popen` at module level.** Replacing the class with a
  function broke `asyncio.windows_utils`, which does
  `class Popen(subprocess.Popen)`. Any `import asyncio` after install
  raised `TypeError: function() argument 'code' must be code, not str`.
  The audit event already covers `Popen` perfectly, so the wrapper was
  both redundant and harmful.
- **`socket` at module level.** Double-counted every lookup and emitted a
  *different event schema* for the same action (no `loopback` key), so a
  consumer reading `event["loopback"]` would `KeyError` on half the
  events.

Both were caught by a canary, not by reading the code.

### Output files

`--record-out` defaults to `docs/fast_gate_runs/<tag>.json`. A3 merged
every run into one file, so a control run and the real run conflated
each other's evidence. Merging is now opt-in (`--record-merge`).

A bug found while doing this: `config.getoption("--record_tag")` never
resolved, because pytest's `_opt2dest` is keyed on the literal dashed
flag. It silently returned the default, so every run wrote `run.json`
regardless of `--record-tag`. Now queried by dest name.

### Aggregation, not truncation

One window enumeration raises hundreds of `ctypes` events. A3's approach
(and my first rewrite) capped the raw list, which is the worst of both:
large files *and* silent loss. Events are now **aggregated** - identical
`(kind, api, target)` collapse into one entry with a `count`. The control
run went from 262KB to 32KB with nothing lost: `user32.EnumWindows` x288
is stored as `count: 288`.

## 3. The canary matrix

`tools/test_record_probe_canaries.py`, 28 canaries, **all passing**.
Skipped unless the recorder is active. Permanent.

| event class | canary |
|---|---|
| `subprocess.Popen` (direct, and via `run`) | 2 |
| `os.startfile` | 1 |
| `os.system` | 1 |
| network `getaddrinfo` / `connect`, loopback flag | 3 |
| ctypes `user32` call, real product path, protocol, exception | 5 |
| `win32gui` - before install / lazy in function / `from x import y` / return value | 4 |
| `pyautogui` - lazy in function, import-time work, product first use, product action | 4 |
| `win32api` input call | 1 |
| selenium start (direct + product first use) | 2 |
| playwright start (direct + product first use) | 2 |
| structural (no printing, no secret reads) | 2 |

Import styles covered: **a)** imported before install, **b)** imported
lazily inside a function (the A3 blind spot), **c)** `from x import y`
after install, **d)** imported by a product module on first use.

### Two canaries that failed for reasons unrelated to the recorder

Recorded because both would have been reported as instrument failures:

1. `assert GetSystemMetrics(0) == 1536` - a **screen width**. Passed in
   isolation, failed in the full run with `1920`. Now compares the
   wrapper against the real function on the same proxy.
2. `ctypes.windll.user32.GetForegroundWindow` - attribute **access**
   is not a call; `CDLL.__getattr__` caches the wrapper, so a second
   read never re-enters the hook. The canary now calls it.

### The transparency guard was itself broken

A3's `test_record_probe_transparency.py` computed its skipif from a
module-level `pytest_configure`. **pytest never calls that hook on a
test module** - only on conftest files and plugins. So the flag stayed
`False`, all 8 tests skipped, and the "transparency 8/8" claim was
**8 skips**, not 8 passes. Both guard files now read the recorder's own
install state. Verified in both directions: 8 skipped without
`--record`, 8 passed with it.

## 4. Documented blind spots

`DOCUMENTED_BLIND_SPOTS` in the canary file, each with its cause:

- **stale `from x import y` binding.** A name bound before install keeps
  the original; no post-hoc wrapping reaches it. Layers 1-2 still fire
  for the underlying OS call, so the event is attributed to the right
  test, just labelled by the library that made the call. Measured
  against this codebase: **zero** occurrences of
  `from <gui module> import <name>`.
- **child processes.** The recorder instruments this interpreter only.
  Relevant: `browser_playwright._probe_chromium_subprocess` and
  `browser_selenium._probe_chromedriver_subprocess` probe in a
  `multiprocessing.Process`.
- **`dll_load` is per-library, not per-call.** Per-call detail comes
  from layer 2.

## 5. Static signal (`docs/fast_gate_static_scan.json`)

`tools/static_scan.py`, pure AST, no imports, no execution. 111 files
scanned, 0 parse errors, 6 files with a signal.

Per-file **and** per-test, where attributable. Scoping matters: the
first version of the cross-check matched on bare method names, so every
class-based test fell back to file-level signals and produced **26**
false disagreements. Scoping correctly reduced that to **2**.

## 6. Dynamic evidence (`docs/fast_gate_evidence.json`)

Collected once under the corrected recorder:

| run | tests | result |
|---|---|---|
| live tier | 444 | 440 passed, 4 xfailed, 21m04s |
| fast tier | 2663 | 2594 passed, 36 skipped |
| controls | 16 | 16 passed |

**All 2663 durations captured**, not top-N. Zero truncated tests.

Controls: the two tests that recorded nothing under A3
(`test_enumerate_real_windows`, `test_get_foreground_real`) now record
**415-421 `user32` calls each**. Transparency: **8/8 actually passing**.

### Cross-check (`docs/fast_gate_cross_check.json`)

- agree: 29
- **static signal, no dynamic event: 2** - both are the recorder's own
  tests, which *assert* that no event fires (they write into a synthetic
  buffer). Explained, not passed over.
- **dynamic event, no static signal: 118** - the product module did it on
  the test's behalf. Named as such.

## 7. The rules (`tools/tiering_rules.py`)

Committed and reviewable, so a classification can be argued with.

- **Harmless executables - a CLOSED set.** Absence from the allowlist
  means not harmless, including for executables never observed. Derived
  from recorded evidence, each with its justification.
  Allowlisted: `cmd.exe` (carries the read-only queries),
  `tasklist` (process enumeration), `ver`, `powershell.exe` **only** for
  `Get-AppxPackage`/`Get-StartApps`/etc.
  Never harmless: `notepad.exe`, `explorer.exe`, browsers, `node.exe`.
- **Duration > 10s** keeps a test `live`.
- **Unexplained static signal** keeps a test `live`.
- **GUI window-station ctypes calls** are forbidden for `runtime`,
  symbol by symbol, in `CTYPES_GUI_SYMBOLS`.

## 8. Result

`docs/tests_tiering.json` - 3107 tests, every one with a tier and a
reason string. `docs/tests_tiering_summary.md` - counts per file per
tier, and every move in both directions.

- `live`: **90** (was 444)
- `runtime`: **3017**

- **388 moved `live` -> `runtime`.**
- **34 moved `runtime` -> `live`** - of which **22 are real
  fast-tier tests** that were running in the gate while touching a real
  window station, a real browser, or the real network:

```
test_phase6_unit.py            6  (EnumWindows, GetForegroundWindow)
test_genesis_arming.py         4  (spawns python.exe subprocesses)
test_level3_9_application_verification.py  3  (explorer.exe, >10s)
test_phase6_failure_injection.py 2  (EnumWindows)
test_gui_window_focus_regression.py 2  (GetForegroundWindow)
test_phase1_contracts_maturity.py   2  (EnumWindows, GetForegroundWindow)
test_import_smoke.py           1  (api.groq.com)
test_phase4_provider_conformance.py 1  (api.groq.com)
test_phase3_control_plane_maturity.py 1  (>10s)
```

The other 12 are the recorder's own canaries, which deliberately fire
GUI/browser/network events and so correctly stay `live` - they are the
instrument, not the thing under test.

### Gate verification

| | before | after |
|---|---|---|
| collected | 3107 | **3107** (reconciles) |
| fast gate | 2615 passed, 48 skipped | **2594 passed, 36 skipped, 477 deselected** |
| live tier | 444 | 477 |

Collection reconciles exactly: 3079 pre-existing + 28 canaries = 3107.
The fast gate is green and its content differs only by the listed moves.
No test body was edited; marks come from `docs/tests_tiering.json` via a
`pytest_collection_modifyitems` hook in `conftest.py`, and a test absent
from the file keeps its current marks.

**T24 correction (2026-10-28):** the moves above were not all real. The
old hook removed `live` from `item.own_markers`, but a module-level
`pytestmark = pytest.mark.live` lives on the parent Module node, so
`item.get_closest_marker("live")` still found it and `-m live` still
collected the "demoted" test. The hook now runs `tryfirst`, writes the
`live` marker down onto every non-demoted descendant, and removes it from
the ancestor. Current collection after that correction and the eight
browser/search tests moved back to `live`: **4542 collected, 4435 fast,
107 live**. Both fast-gate orderings are green.

### The honest headline

**94% of the old `live` bucket needed no real external application,
browser, or network** - the same order as A2's estimate, now established
by recorded evidence rather than by a probe with a known false-positive
rate. And **22 tests that should never have been in the fast gate were
in it**, doing real GUI and network work while the gate reported green.

---

# Continuation A5 - the tripwire

## 1. Why A4 was not enough

A4 classified the tests that existed. It could not stop the next one
from arriving unclassified. `docs/tests_tiering.json` is a snapshot: a
test written tomorrow is not in it, keeps no marks, and therefore lands
in the fast gate by default.

A4 had already proven that default is unsafe -- 22 fast-tier tests were
touching a real window station, a real browser and the real network
while the gate reported green. Nothing stopped the 23rd.

## 2. The tripwire

`tools/tripwire_plugin.py`, loaded automatically by
`backend/conftest.py` via `pytest_plugins`. **No flag is needed to turn
it on** -- a gate that must be switched on is a gate that gets switched
off. `--no-tripwire` exists for bisecting a suspected false positive
and is documented as not-a-CI-answer.

An autouse fixture, for every test not marked `live`, attaches a capture
frame to `record_probe` and judges the events at the end of the body.

It fails at the end of the test, never at the call site. That is the
whole reason the A2 blocking probe was abandoned: a block raised inside
an async task surfaces as a playwright `TargetClosedError` and the real
cause is swallowed. Recording first and judging afterwards cannot
swallow anything.

### Reported as FAILED, not as a teardown ERROR

Measured before designing this: pytest runs a plugin's
`pytest_runtest_teardown` BEFORE fixture teardown. So raising in a
finalizer produced `3 passed, 3 errors` -- the offending test still
counted as **passed**, and a gate summary could read green. The check
therefore runs in a `pytest_runtest_call` hookwrapper, which yields an
ordinary failure. A second check in the fixture finalizer catches
anything reached during teardown, by comparing event counts across the
two moments.

### Multiple capture frames

`record_probe` now writes each event to every attached frame. The
recorder plugin and the tripwire need the same events and tear down at
different moments; whichever finished first would otherwise find the
buffer emptied.

### Bug found by the scratch tests, not by reading

The first version of the audit-hook guard was:

```python
if not _ACTIVE or _CURRENT["nodeid"] is None:
    return
```

That consults only the RECORDER's frame. With the recorder idle and
only the tripwire attached, the hook returned early and dropped every
event. Result: the ctypes scratch test failed as expected, and the
**network scratch test silently passed**. A guard that reads the wrong
source of truth is worse than no guard, because it looks like it works.

## 3. Does it catch unmarked offenders

Three scratch tests, no marks, absent from `tests_tiering.json`. They
live in `tools/fixtures/tripwire_offenders_scratch.py` -- deliberately
NOT named `test_*.py`, because a file meant to fail must not be
collected by an ordinary run.

| scratch test | event class | result |
|---|---|---|
| `test_scratch_non_loopback_network_is_caught` | non-loopback network | **FAILED by name** |
| `test_scratch_non_allowlisted_executable_is_caught` | non-allowlisted exe | **FAILED by name** |
| `test_scratch_ctypes_window_station_is_caught` | `user32` via ctypes | **FAILED by name** |

`203.0.113.1` is RFC 5737 TEST-NET-3 -- reserved for documentation and
guaranteed unroutable, so the attempt exercises DNS and the network
stack without contacting anything real.

The failure message names the actual event (`203.0.113.1`,
`hostname.exe`, `user32.GetForegroundWindow`) and gives the two
legitimate ways out: mark the test `live`, or allowlist the executable
**with a reason** in `tools/tiering_rules.py`.

`tools/test_tripwire_mutation.py` (9 tests) runs the offenders in a
child process and asserts all three fail by name, that the message
names the cause, that the offenders really are unmarked, and that the
exemption list has not quietly widened.

### Overhead

| | seconds |
|---|---|
| fast tier with tripwire | 93.5 / 93.8 / 93.0 |
| fast tier without | 93.6 / 92.7 / 93.5 |
| **difference** | **within noise (0.1s, 0.1%)** |

Instrumented directly: **0.02 ms per test** (fixture setup + teardown
only). The first version of that figure timed the whole fixture span,
which includes the test body, and would have reported the suite's own
90-second runtime back as the tripwire's cost.

## 4. What the tripwire found that A4's evidence missed

**19 fast-tier tests construct a GUI provider and the recorded evidence
caught none of them.**

Cause, measured directly: importing `pyautogui` performs ~110 calls to
`user32.VkKeyScanA` **once per process**. Verified:

```
FIRST  GUIController: ctypes_call = 10  VkKeyScanA = 1
SECOND GUIController: ctypes_call = 0   VkKeyScanA = 0
```

So the GUI cost is charged to whichever test happens to trigger the
first import, and every later test looks clean. A4's evidence run had an
earlier importer, so it recorded zero events for all 19.

A dynamic rule that depends on collection order is not a rule. The fix
is a **static** one: `static_scan.py` now emits a `gui_construct`
signal for `GUIController`, `WindowsGUIProvider`, `UIAutomationProvider`,
`GUIObserver`, `GUIVerifier`, and `unexplained static signal keeps a
test live` handles it. 26 tests moved to `live` on that signal.

`tools/find_gui_first_touch.py` is the sweep: find candidates
statically, then re-run each in its own process where it is guaranteed
to be first.

## 5. A bug in A4's own mark application

With the GUI tests moved out, one more offender surfaced --
`test_unseen_task_semantic.py::test_anaphoric_move_plan_is_valid`.
That test carries an explicit `@pytest.mark.live` **with a docstring**
explaining that it builds a real `GenesisOS` whose browser probe reaches
the network.

A4's `conftest.py` hook saw `tier == "runtime"` and **stripped the
marker**, because the evidence -- blinded by the one-shot import --
said the test was harmless. The tripwire then failed the test it had
just been promoted into.

The hook now distinguishes the two cases:

- a **module-level** `pytestmark = pytest.mark.live` is a coarse bucket
  applied to a whole file; overriding it from evidence is the point of
  the tiering;
- a **function-level** `@pytest.mark.live` is a deliberate statement
  about one test, and is never demoted. It is counted and reported in
  the terminal summary instead.

Overwriting a human statement with a measurement that has a known blind
spot is the wrong direction for a safety gate.

## 6. Exemptions

Explicit, enumerated in `tiering_rules.py`, and audited by four tests
in `tools/test_tripwire_mutation.py`:

- **Recorder self-tests** -- the two `tools/test_record_probe_*.py`
  files, exempt from `process`, `dll_load`, `ctypes_call` ONLY. A `gui`,
  `browser`, `network` or `os_launch` event still holds them `live`,
  which is why 11 canaries and 1 transparency test are correctly in the
  live tier.
- **`sys.executable` by absolute path.** A test that spawns the
  interpreter it is itself running is building test infrastructure, not
  reaching an external capability. Narrow on purpose: the bare name
  `python.exe` is NOT allowlisted, so a test cannot ship its own script
  and gain arbitrary execution while looking clean. Needed by
  `test_require_passed.py` and `test_tripwire_mutation.py`.

Nothing else is exempt. Tested.

## 7. No-vacuous-pass guard

`tools/require_passed.py`. A required set must **run and pass**;
skips, xfails, xpasses, errors and deselections are all failures.

A3's "transparency 8/8" was 8 skips. That is the shape this script
exists to make impossible to repeat.

Six required sets, each stating what a false pass would mean:

| set | mode |
|---|---|
| `recorder_transparency` | `--record -p record_probe` |
| `recorder_canaries` | `--record -p record_probe` |
| `tripwire_mutation` | default |
| `class_census` | default |
| `approval_channel` | default |
| `workspace_boundary` | default |

All six currently **OK**, exit 0.

`tools/test_require_passed.py` (12 tests) proves it bites, including
end to end: `recorder_transparency` is run WITHOUT `--record` -- exactly
A3's mistake -- and the guard is shown to catch the all-skipped set
while pytest itself exits 0.

Getting there required fixing two real bugs: `findall` returning one
tuple per regex alternative, and a summary-line scan that looked only
for "passed"/"failed" and so walked straight past `8 skipped in 0.20s`
-- reporting zeros, which is indistinguishable from "nothing ran", i.e.
another false pass.

## 8. Tier table

| tier | tests |
|---|---:|
| fast (`-m "not live"`) | 2643 |
| live (`-m live`) | 485 |
| **collected** | **3128** |

`tests_tiering.json`: 3030 `runtime`, 98 `live`, summing to 3128.

**+21 since A4's 3107**, all harness: `tools/test_tripwire_mutation.py`
(9) and `tools/test_require_passed.py` (12). They were recorded under
the recorder and merged so the table reconciles exactly.

### Runtimes

| tier | tests | seconds |
|---|---:|---:|
| compileall | - | 0.35 |
| fast | 2643 | 101 |
| medium | 2643 + live import smoke | ~102 |
| live | 485 | 1519 |
| full | 3128 | 1546 |

### The medium-tier decision

The directive's premise was that import smoke is ~100 s and sits
outside the fast tier, and that medium should drop it if fast + import
smoke exceeds ~5 minutes.

**Measured, the premise does not hold.** Import smoke is already inside
the fast tier: **217 of its 218 tests are already collected by
`-m "not live"`**, and run standalone it costs **11 s**, not 100 s.

So medium == fast, at ~102 s, comfortably under 5 minutes. Import smoke
stays. Adding it as a separate medium step would buy nothing; the one
import-smoke test that is `live`-marked is the only thing medium adds.

### Which tier is `test_pure_level3_objectives_do_not_invoke_agents`?

**`live`.** Its name says it invokes nothing; the evidence says
otherwise. Constructing the runtime fires
`playwright.sync_api.sync_playwright`, plus `tasklist` for `chrome.exe`
and two read-only PowerShell registry queries, and it runs for 22.4 s.

### Does runtime construction still probe a browser in a `runtime` test?

**No.** Across all 3030 `runtime` tests, the recorded evidence shows:

| event class | count |
|---|---:|
| browser launch | **0** |
| GUI library call | **0** |
| `os.startfile` | **0** |
| non-loopback network | **0** |
| loopback network | 43 (own fixture servers) |

So the provider-probe stub contemplated for the `runtime` tier is **not
needed**: the evidence does not show one, and adding it would suppress
the very signal that would reveal it appearing later.

## 9. Verification

| check | result |
|---|---|
| fast tier | 2607 passed, 36 skipped, 485 deselected |
| fast tier, `.env` absent + provider keys unset | 2605 passed, 38 skipped, 485 deselected |
| live tier | 461 passed, 12 skipped, 4 xfailed (489) |
| full default order | **3076 passed, 48 skipped, 4 xfailed** |
| collection reconciles | 3128 = 2643 + 485 |
| required sets | 6/6 OK |
| canaries | 28 passed |
| transparency | 8 passed |

### Mutation

`GenesisOS.classify` renamed away, fast tier run, restored.

```
1 failed, 2606 passed, 36 skipped, 485 deselected
FAILED test_structural_census.py::test_core_class_keeps_its_public_members[GenesisOS]
```

The gate went red, which is the requirement. But **the catch is shallow
and that is the honest finding**: exactly one test noticed, and that
test only asserts the member still EXISTS. No behavioural test in the
medium tier exercises `GenesisOS.classify`. A rename is the mildest
possible mutation and it is caught by a name check alone; the coverage
behind the system's primary entry point is thinner than a green gate
suggests.

## Residual list (open)

| item | status |
|---|---|
| `test_browser_manager_has_three_concrete_providers` | **STILL FLAKY. Not fixed.** |

Root cause is **two** load-sensitive mechanisms, not one. B1's
`deterministic_provider_probes` fixture removes the first and not the
second, and this is stated in the fixture's own docstring so it is not
mistaken for a fix.

1. **Probe cache.** `PlaywrightBrowserProvider._check_availability` (and
   the selenium equivalent) spawn a child process and join it with
   `proc.join(timeout=5.0)`. The result -- *including a timeout* -- is
   cached in a module-level `_probe_cache` for the life of the process.
   Under contention the probe exceeds five seconds, is terminated, and
   the timeout is cached as "unavailable" permanently.
   *Proposal (Phase 5):* a TTL on the cache, and never cache a timeout
   as a definitive answer.

2. **Provider construction timeout.** `BrowserManager.__init__` wraps
   provider construction in `_PROVIDER_PROBE_TIMEOUT = 10.0` and, per
   its own comment, "abandons a probe that cannot finish in this window
   rather than allow it to block construction".
   `GenesisOS._build_minimal_browser()` then substitutes a
   webbrowser-only manager.

Measured with the fixture attached: **20/20 green in isolation, 8/8
under 3x CPU load, and still failing in the full default-order run**,
with `provider_names == ['webbrowser']` -- the signature of mechanism 2,
not mechanism 1.

Controlling mechanism 2 means changing product behaviour, which this
effort may not do. Proposed for Phase 5: make the fallback observable
(a `degraded=True` flag on `BrowserManager`) so a test can assert on the
degraded mode rather than accidentally depending on it.

| item | status |
|---|---|
| `import pyautogui` one-shot cost | order-dependence caveat, see below |

`import pyautogui` performs ~110 `user32.VkKeyScanA` calls **once per
process**. Verified: first `GUIController()` records them, the second
records nothing. Consequence for any future evidence run: the GUI cost
is charged to whichever test happens to trigger the first import, and
every later test looks clean. This is why the `gui_construct` signal in
`tools/static_scan.py` is STATIC -- a dynamic rule that depends on
collection order is not a rule. Any new evidence run must either run
candidates in isolation or keep the static signal.

---

# Continuation B1

## Behavioural coverage for the entry point

`test_genesis_entrypoint_behavior.py`, 12 tests, all fast-tier and
tripwire-clean **with no exemption**.

Built on two `conftest.py` fixtures:

- `hermetic_capabilities` (session) stubs `sys.modules["pyautogui"]`
  with a pure-Python module -- so `import pyautogui` never reaches the
  real module and never performs its import-time keyboard probe -- and
  pins the browser provider `_probe_cache` so no subprocess probe runs.
- `genesis_runtime` (module) constructs a real `GenesisOS` on top of it,
  in about 9 s, once per module.

Verified hermetic: after construction plus two `classify` calls the
recorder reports **zero events**.

## Mutations, and one the tests did not catch

`tools/run_behavior_mutations.py`, three mutations, each restored.

| mutation | result |
|---|---|
| `classify` renamed away | **CAUGHT** -- 4 behavioural tests failed by name |
| `classify` returns Level 3 for everything | **CAUGHT** -- 4 behavioural tests failed by name |
| `run_level3` skips the boundary check | **MISSED** |

The third is the honest finding. The boundary test asserted only
`dispatches == []` and passed **vacuously**: `run_level3` never resolved
the operation, answering "could not resolve that request to an available
registered capability", so the boundary was never consulted. The
mutation is what exposed that. A non-vacuity assertion has been added,
and the test now also fails if the request is not understood -- but
`run_level3` still does not reach the boundary for this input, so the
gap is real and is carried forward.

### Bugs the harness itself had

- `genesis.py` is a **mixed line-ending** file: the `run_level3` block is
  CRLF, the `classify` block is LF. An LF-only mutation pattern silently
  did not match and the harness reported `SKIP` -- which reads like an
  honest result rather than an instrument that never fired.
- Two `pytest_collection_modifyitems` definitions in `conftest.py`.
  Python binds only the last, so the probe fixture was never attached to
  any test while sitting in the file looking correct. Same class as the
  duplicate `pytest_terminal_summary` in A4.
- `test_verify_all.py` called `va.required_sets()` and passed pytest an
  **empty target list**. pytest with no path arguments collects the whole
  rootdir, so a "cheap" test ran the entire suite from inside itself: the
  full default-order run went from 25 minutes to **four hours**, and the
  nested runs interfered with the probes they were measuring. Now
  structural only; a test about a gate must not itself be a gate.

## `calculator.py`

Archived to `tools/archive/calculator.py.md` with a note. No code
referenced it outside `test_import_smoke.py`'s own exclusion, which was
created by this effort; `NON_MODULE_PY_FILES`, its entry in
`PRODUCT_MODULES`, and its guard test are removed. There is deliberately
no replacement allowlist: a `.py` file that is not a module should not
exist in the product tree, so the next one fails import smoke outright.

## `verify_all`

`tools/verify_all.py --fast`: seal, required sets, compileall, fast
tier. `--full` adds the live tier, both orderings, and a before/after
file-manifest check.

```
component                               passed  skipped xfailed  failed   rc     sec  result
--------------------------------------------------------------------------------------------
seal:run_safety_verify                       0        0       0       0    0   209.4  OK
required sets (no skips allowed)             0        0       0       0    0    76.0  OK
compileall                                   0        0       0       0    0     0.4  OK
fast tier                                 2626       35       0       0    0   163.3  OK

RESULT: PASS
```

`tools/test_verify_all.py` (7 tests) proves it rejects a vacuous
required set: `recorder_transparency` run without `--record` gives 8
skips and pytest exit 0, and the gate's rule rejects it.

---

## Appendix: Continuation A4 (historical)

### A4's blind spot

A3's recorder wrapped `win32gui`, `pyautogui`, `selenium.webdriver`
and `playwright.sync_api` via `sys.modules` at install time. They were
not there: the code under test imports all four lazily, inside
functions. Two control tests recorded nothing.

Two deeper defects, found only by writing canaries:

- **The product does not use `win32gui` for window work.**
  `window_models.py` and `application_state_machine.py` call
  `ctypes.windll.user32` directly. Fixing only the import timing would
  have produced a recorder that looked healthy and still reported zero
  GUI events. There is no `ctypes.call_function` audit event in CPython
  3.12 (verified), so the observation point is `ctypes.CDLL.__getattr__`.
- **Importing `pyautogui` is itself a GUI action** -- ~110
  `user32.VkKeyScanA` calls. This is also the one-shot cost A5 later had
  to compensate for statically.

### Two wrappers that had to be removed

- **`subprocess.Popen` at module level** broke
  `asyncio.windows_utils`, which does `class Popen(subprocess.Popen)`;
  any `import asyncio` after install raised `TypeError`. The audit
  event already covers `Popen`.
- **`socket` at module level** double-counted lookups and emitted a
  *different event schema*, so `event["loopback"]` would `KeyError`.

### A4's own transparency guard was broken

A3 computed its skipif from a module-level `pytest_configure`. pytest
never calls that hook on a test module, so the flag stayed `False`, all
8 tests skipped, and "transparency 8/8" was **8 skips**.

### Canary matrix (28, all passing)

skipped unless the recorder is active:

| event class | canaries |
|---|---|
| `subprocess.Popen` direct and via `run` | 2 |
| `os.startfile` | 1 |
| `os.system` | 1 |
| network `getaddrinfo` / `connect` / loopback flag | 3 |
| ctypes: `user32`, real product path, protocol, exception, attr passthrough | 5 |
| `win32gui`: before install / lazy in function / `from x import y` / return value | 4 |
| `pyautogui`: lazy in function, import-time work, product first use, product action | 4 |
| `win32api` input call | 1 |
| selenium start: direct + product first use | 2 |
| playwright start: direct + product first use | 2 |
| structural | 2 |

Import styles covered: imported before install, imported lazily inside a
function, `from x import y` after install, and imported by a product
module on first use.

### A4 result

444 `live` -> 90. 388 moved to `runtime`, 22 real fast-tier tests moved
to `live`. Collection 3107. Fast gate 2594 passed.

---

## Appendix: Continuation A1-A3 (historical)

### Method

`tools/probe_plugin.py` - opt-in only, never loaded in a normal run.
Blocks capabilities by raising, so a test that genuinely needs one fails
loudly rather than degrading into a vacuous pass.

| probe | denies | evidence produced |
|---|---|---|
| A `--probe-network` | `socket.socket.connect`, `connect_ex`, `sendto`, `create_connection`, `getaddrinfo`, `gethostbyname` | test fails -> group (a) |
| B `--probe-gui` | `subprocess.Popen/run/call/check_output`, `os.system/startfile/spawn*/exec*`, plus real entry points of `pyautogui`, `win32gui`, `win32api`, `playwright.sync_api`, `selenium.webdriver` | test fails -> group (b) |
| both | - | test passes -> candidate (c) |

### The blocker that stopped A2

Step 2.6 required the new fast gate to pass under Probes A and B
together. It did not: `47 failed, 2332 passed`. The cause was that
Probe B patches `subprocess.run` and `os.system` at library level, so
any test whose import chain touches subprocess incidentally is caught.
**Blocking was the wrong instrument**; A3 replaced it with a recorder.

The narrowing Probe B asked for is now implemented as an allowlist of
specific entry points in `tools/tiering_rules.py`, derived from recorded
evidence rather than guessed.