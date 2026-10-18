"""Item 15B (S13): the human-approval channel was dead on Windows.

`_read_line` bounded its wait with `select.select([stream], [], [], timeout)`.

On Windows, `select()` supports SOCKETS ONLY. Passing a file handle
raises `OSError [WinError 10093]`. That is not an edge case -- it is
every console on the platform. Measured on this machine, a real console:

    sys.stdin.isatty()                              -> True
    select.select([sys.stdin], [], [], 1.0)         -> OSError 10093

The old handler caught that OSError and raised TimeoutError, which
`request_approval` maps to `denied`. So on Windows a human could never
approve anything: a genuine interactive console produced exactly the
same outcome as a closed pipe, and every Tier 1 action was
unapprovable by construction.

The failure was invisible because it looked like correct fail-closed
behaviour. A denial is the safe answer; a denial that is the ONLY
possible answer is not safety, it is a dead switch wearing a safety
label.

The fix bounds the wait with a reader thread and join(timeout), which
works on win32 and -- unlike msvcrt console polling -- works with an
INJECTED stream, which is what makes this testable at all.

These tests use a fake TTY-like console, so they are meaningful on
every platform and do not depend on which one CI happens to run.
"""
from __future__ import annotations

import io
import sys
import threading
import time

import pytest

from genesis_os.approval_channel import ApprovalChannel


APPROVE_PHRASE = "approve"


class FakeConsole(io.StringIO):
    """A stream that claims to be a TTY and optionally blocks.

    `select()` refuses to touch it on any platform, because StringIO
    has no real fileno -- which is exactly the property that made the
    old code unusable.
    """

    def __init__(self, initial: str = "", *, block: bool = False):
        super().__init__(initial)
        self._block = block
        self.readline_calls = 0

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        raise OSError("no real fileno")

    def readline(self, *a, **k):
        self.readline_calls += 1
        if self._block:
            threading.Event().wait(30)
        return super().readline(*a, **k)


class NonTTY(io.StringIO):
    """A pipe-like stream. isatty() is False, as for `echo x | ...`."""

    def isatty(self) -> bool:
        return False


class ExplodingTTY(io.StringIO):
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        raise OSError("no real fileno")

    def readline(self, *a, **k):
        raise RuntimeError("the console exploded")


def _channel(stdin, timeout=2.0, require_tty=True):
    return ApprovalChannel(
        stdin=stdin,
        stdout=io.StringIO(),
        timeout=timeout,
        require_tty=require_tty,
    )


def _request(channel, operation="file.delete", arguments=None):
    from genesis_os.approval_channel import ApprovalRequest

    args = dict(arguments if arguments is not None else {"path": "C:/x"})

    return channel.request_approval(
        ApprovalRequest(
            operation=operation,
            arguments=args,
            arguments_hash=f"hash:{operation}",
            plan_target=args.get("path"),
            tier="1",
            blast_radius_reason="irreversible",
        )
    )


# --------------------------------------------------------------------------
# The defect: a real console must be able to approve
# --------------------------------------------------------------------------

def test_a_tty_console_can_approve():
    """Before this item, this denied on Windows."""
    stdin = FakeConsole(f"{APPROVE_PHRASE}\n")
    channel = _channel(stdin)

    result = _request(channel)

    assert result["approved"] is True, (
        "a real interactive console could not approve; the approval "
        f"channel is still dead on this platform: {result}"
    )
    assert result["decision"] == "approved", result


def test_a_tty_console_can_deny_by_typing_something_else():
    stdin = FakeConsole("no\n")
    channel = _channel(stdin)

    result = _request(channel)

    assert result["approved"] is False, result


def test_the_read_actually_happened():
    """Guards against 'approved' arriving without consuming the stream."""
    stdin = FakeConsole(f"{APPROVE_PHRASE}\n")
    channel = _channel(stdin)

    assert _request(channel)["approved"] is True
    assert stdin.readline_calls >= 1, "the stream was never read"


# --------------------------------------------------------------------------
# select() is genuinely unusable here, which is the point
# --------------------------------------------------------------------------

def test_select_cannot_be_used_on_this_stream():
    """The premise. If select() ever worked here, the fix's rationale goes."""
    import select

    with pytest.raises(Exception):
        select.select([FakeConsole()], [], [], 0.1)


def test_the_approval_path_does_not_call_select():
    """Structural: select must not reappear in the read path."""
    import inspect

    source = inspect.getsource(ApprovalChannel)

    assert "import select" not in source, (
        "select() is back in the approval channel; it cannot bound a "
        "text stream on Windows"
    )


# --------------------------------------------------------------------------
# Fail-closed is preserved
# --------------------------------------------------------------------------

def test_a_non_tty_stream_is_still_denied():
    stdin = NonTTY(f"{APPROVE_PHRASE}\n")
    channel = _channel(stdin)

    result = _request(channel)

    assert result["approved"] is False, (
        "a non-interactive stream approved something"
    )


def test_a_non_tty_is_denied_even_with_the_phrase_typed_in():
    """`echo approve | genesis` must not approve."""
    stdin = NonTTY(f"{APPROVE_PHRASE}\n")
    channel = _channel(stdin)

    result = _request(channel)

    assert result["approved"] is False, result


def test_a_timeout_is_a_denial():
    """A human who walks away must not accidentally authorise."""
    stdin = FakeConsole(block=True)
    channel = _channel(stdin, timeout=0.4)

    started = time.time()
    result = _request(channel)
    elapsed = time.time() - started

    assert result["approved"] is False, result
    assert elapsed < 8.0, (
        f"the bounded read took {elapsed:.1f}s; the timeout is not "
        "actually bounding anything"
    )


def test_a_stream_that_raises_is_a_denial_not_a_crash():
    stdin = ExplodingTTY()
    channel = _channel(stdin)

    result = _request(channel)

    assert result["approved"] is False, (
        "a broken console crashed or approved instead of denying"
    )


def test_eof_is_a_denial():
    stdin = FakeConsole("")  # immediately at EOF
    channel = _channel(stdin)

    result = _request(channel)

    assert result["approved"] is False, result


def test_an_exhausted_stream_does_not_approve_on_a_second_prompt():
    channel = _channel(FakeConsole(""))

    first = _request(channel)
    second = _request(channel, operation="folder.delete")

    assert first["approved"] is False
    assert second["approved"] is False


# --------------------------------------------------------------------------
# The real system stdin path must work too
# --------------------------------------------------------------------------

def test_the_default_sys_stdin_path_is_also_bounded(monkeypatch):
    """No injected stream: the fix must cover the production path."""
    stdin = FakeConsole(f"{APPROVE_PHRASE}\n")
    monkeypatch.setattr(sys, "stdin", stdin)

    channel = ApprovalChannel(stdout=io.StringIO(), timeout=2.0)

    result = _request(channel)

    assert result["approved"] is True, result


def test_blocking_sys_stdin_still_times_out(monkeypatch):
    stdin = FakeConsole(block=True)
    monkeypatch.setattr(sys, "stdin", stdin)

    channel = ApprovalChannel(stdout=io.StringIO(), timeout=0.4)

    started = time.time()
    result = _request(channel)
    elapsed = time.time() - started

    assert result["approved"] is False
    assert elapsed < 8.0, f"took {elapsed:.1f}s"


# --------------------------------------------------------------------------
# The denial is recorded honestly
# --------------------------------------------------------------------------

def test_a_timeout_is_recorded_as_a_timeout():
    channel = _channel(FakeConsole(block=True), timeout=0.4)

    result = _request(channel)

    assert result["approved"] is False
    note = (result.get("note") or "").lower()
    assert "timed out" in note or "timeout" in note, result


def test_a_non_tty_denial_says_why():
    channel = _channel(NonTTY(f"{APPROVE_PHRASE}\n"))

    result = _request(channel)

    assert result["approved"] is False
    note = (result.get("note") or "").lower()
    assert note, "a denial carried no reason"


# --------------------------------------------------------------------------
# Structural guard against regressing to a blocking read
# --------------------------------------------------------------------------

def test_the_bounded_read_uses_a_thread_and_a_join():
    import inspect

    source = inspect.getsource(ApprovalChannel._read_line_bounded)

    assert "threading.Thread" in source, (
        "the bounded read no longer uses a reader thread"
    )
    assert ".join(" in source, (
        "the bounded read does not join with a timeout, so it cannot "
        "bound anything"
    )
    assert "select" not in source, "select() is back in the bounded read"


def test_an_unbounded_read_is_still_possible_when_no_timeout_is_set():
    """`timeout=0` is the documented escape hatch; keep it working."""
    stdin = FakeConsole(f"{APPROVE_PHRASE}\n")
    channel = _channel(stdin, timeout=0)

    assert _request(channel)["approved"] is True