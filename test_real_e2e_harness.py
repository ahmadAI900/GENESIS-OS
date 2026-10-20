"""
ITEM 19A (T16) -- the benchmark harness must not be able to lie.

benchmark/real_e2e.py used to print the literal
"Real end-to-end boot: PASS" and `return 0` no matter what the run
actually did, while its docstring claimed both "This is NOT a mock"
and "The only mocked layer is the OS" (neither is true: nothing is
mocked, and the real OSManager is simply never executed). It also
could not even terminate: GenesisOS starts non-daemon threads and
exposes no shutdown API, so sys.exit hung and no exit code was ever
observable.

The fixed harness derives its verdict from real per-check results
(the SAMPLES table carries each tag's expected level), prints
RESULT: PASS / RESULT: FAIL accordingly, exits non-zero on any
failure, and hard-exits after flushing so the process status IS the
verdict. Tests drive main() through a stub GenesisOS.
"""
from pathlib import Path

import benchmark.real_e2e as real_e2e


class _FakeRegistry:
    def __init__(self, agents):
        self._agents = agents

    def count(self):
        return len(self._agents)

    def get_all_agents(self):
        return self._agents


class _FakeOSManager:
    def __init__(self, status):
        self._status = status

    def status(self):
        return self._status


def _agent(i):
    class _A:
        name = f"Agent {i}"

    return _A()


def _make_fake_genesis(*, good):
    class FakeGenesisOS:
        shutdown_calls = []

        def __init__(self):
            if good:
                self.brain = object()
                self.memory = object()
                self.conversation = object()
                self.registry = _FakeRegistry([_agent(i) for i in range(10)])
                self.os_manager = _FakeOSManager({"level": 3, "version": "stub"})
            else:
                self.brain = None
                self.memory = None
                self.conversation = None
                self.registry = _FakeRegistry([])
                self.os_manager = _FakeOSManager({})

        def shutdown(self):
            FakeGenesisOS.shutdown_calls.append(self)

        def classify(self, text):
            if good:
                for _tag, sample_text, expected in real_e2e.SAMPLES:
                    if sample_text == text:
                        return {
                            "level": expected[0],
                            "mode": "stub",
                            "agent": None,
                            "agents": [],
                            "intent": None,
                        }
                raise AssertionError(f"unexpected sample text {text!r}")
            return {"level": 99, "mode": "bogus"}

    return FakeGenesisOS


def test_forced_failure_exits_nonzero_with_no_pass_lines(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        real_e2e.genesis_module,
        "GenesisOS",
        _make_fake_genesis(good=False),
    )

    rc = real_e2e.main()
    out = capsys.readouterr().out

    assert rc != 0, "a run whose every check failed must exit non-zero"
    assert "[PASS]" not in out, "failed checks must not emit a PASS line"
    assert "RESULT: PASS" not in out
    assert "RESULT: FAIL" in out


def test_genuine_pass_exits_zero_with_derived_pass_result(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        real_e2e.genesis_module,
        "GenesisOS",
        _make_fake_genesis(good=True),
    )

    rc = real_e2e.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "RESULT: PASS" in out
    assert "RESULT: FAIL" not in out
    assert "[FAIL]" not in out, "a clean run must not print any FAIL line"


def test_main_shuts_the_runtime_down(monkeypatch):
    """Item 21C (C36): the harness must stop what it booted.

    Booting the real runtime and hard-exiting without teardown is
    how driver sessions and watchers leaked; main() now calls
    shutdown() before returning (the os._exit in __main__ stays as
    a last resort for abandoned threads).
    """
    genesis_cls = _make_fake_genesis(good=True)
    monkeypatch.setattr(
        real_e2e.genesis_module, "GenesisOS", genesis_cls
    )

    real_e2e.main()

    assert genesis_cls.shutdown_calls, (
        "main() never called the runtime's shutdown(); the harness "
        "boots a real runtime and must stop it before exiting"
    )


def test_boot_crash_returns_nonzero_result(monkeypatch, capsys):
    class ExplodingGenesisOS:
        def __init__(self):
            raise RuntimeError("boot exploded")

    monkeypatch.setattr(
        real_e2e.genesis_module, "GenesisOS", ExplodingGenesisOS
    )

    rc = real_e2e.main()
    out = capsys.readouterr().out

    assert rc == 1, "a boot crash must be reported as a failing exit code"
    assert "RESULT: FAIL" in out
    assert "boot exploded" in out


def test_source_has_no_hardcoded_pass_and_can_exit_non_zero():
    src = Path(real_e2e.__file__).read_text(encoding="utf-8-sig")

    assert 'Real end-to-end boot: PASS' not in src, (
        "the hardcoded PASS banner is back"
    )
    assert "RESULT: FAIL" in src, "no derived failure verdict exists"
    assert "os._exit" in src, (
        "without a hard exit the process hangs on the runtime's "
        "non-daemon threads and no exit code is observable"
    )


def test_source_documents_the_run_honestly():
    src = Path(real_e2e.__file__).read_text(encoding="utf-8-sig")

    assert "NOT a mock" not in src, "the contradictory mock claim is back"
    assert "only mocked layer" not in src.lower(), (
        "nothing is mocked; the OS must not be called the mocked layer"
    )
    assert "READ-ONLY" in src, "the read-only contract must be stated"


def test_source_compiles_without_syntax_warning():
    path = Path(real_e2e.__file__)
    src = path.read_text(encoding="utf-8-sig")

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(src, str(path), "exec")
