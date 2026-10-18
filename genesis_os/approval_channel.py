"""Human approval channel (minimal).

Phase 13 (Human Escalation) work pulled forward, the same way the Phase 11
bridge was labelled. This is deliberately MINIMAL: one prompt, read from
the REPL's real stdin, that either approves the exact plan it displayed
or denies it. Workflow state, confidence thresholds and ambiguity
escalation stay out of scope.

WHY THIS MODULE IS SEPARATE AND SMALL
-------------------------------------
Every property below is a security property of the *channel*, not of the
model. The module exists as its own unit so that a structural test can
assert property 1: nothing outside the runtime's approval path may call
``ApprovalStore.approve()``.

THE FIVE PROPERTIES THAT MATTER MOST
------------------------------------
1. Only a human channel approves. ``approve_human_request`` is the ONLY
   sanctioned caller of ``ApprovalStore.approve()`` in the product, and
   it refuses unless handed a request this module itself minted from a
   hash-bound plan.
2. Prompt content is derived, never model-written. :func:`render_prompt`
   builds text only from the plan's own fields plus filesystem facts. It
   never accepts a caller-supplied description.
3. Protected paths are visibly distinct and need a typed phrase.
4. Non-interactive contexts deny. No TTY, closed/empty stdin, EOF, or
   timeout all deny. There is deliberately no auto-approve flag, env
   var, or config option -- :func:`auto_approve_option_names` exists so a
   test can assert none exists.
5. Tool output cannot answer the prompt. Buffered stdin is discarded
   before the read, so a type-ahead "y" emitted by a tool cannot
   approve.

Plus: single-use and argument-bound (property 6, enforced by the
existing AuthorizationGrant), no repeat-prompt within a turn (7), and an
append-only audit log that records hashes and paths but never file
contents or secrets (8).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from genesis_os.approval_store import ApprovalStore
from genesis_os.authorization_grant import issue_authorization_grant
from genesis_os.workspace_boundary import (
    arguments_escape_workspace,
    path_is_protected,
    workspace_root,
)

__all__ = [
    "ApprovalRequest",
    "ApprovalChannel",
    "render_prompt",
    "auto_approve_option_names",
    "PROTECTED_PHRASE",
    "append_audit",
    "read_audit",
]

# Typed confirmation for protected paths. Deliberately not "y".
PROTECTED_PHRASE = "I understand this modifies Genesis"

# If any of these ever appears as a config key, property 4 is broken:
# someone added a way to auto-approve.
FORBIDDEN_AUTO_APPROVE_NAMES = (
    "GENESIS_AUTO_APPROVE",
    "GENESIS_ASSUME_YES",
    "GENESIS_SKIP_CONFIRMATION",
    "GENESIS_YES",
    "GENESIS_NONINTERACTIVE_APPROVE",
    "genesis_auto_approve",
    "auto_approve",
    "assume_yes",
    "skip_confirmation",
)


def auto_approve_option_names() -> frozenset:
    """Names that must never become an approval bypass. Asserted absent."""
    return frozenset(FORBIDDEN_AUTO_APPROVE_NAMES)


# ---------------------------------------------------------------------------
# Audit log (property 8): append-only, hashes and paths, never contents.
# --------------------------------------------------------------------------
# Location is configurable and defaults OUTSIDE the source tree.
#
# Before 2026-10-14 the path was hardcoded to
# `Path(__file__).parent / "approval_audit.jsonl"`, i.e. inside
# `genesis_os/`. Two consequences, both real: every test that dispatched
# an approval-gated action appended to the repository (23 tests in
# test_approval_channel.py alone), and the source tree therefore stopped
# being byte-stable between runs, so it could not be verified against a
# sealed backup.
#
# Resolution order:
#   1. $GENESIS_APPROVAL_AUDIT_LOG, if set. May be a file or a directory
#      (a directory receives the default filename inside it).
#   2. the workspace root's audit area, if the boundary is configured
#   3. the system temp directory - the last resort, so a machine with no
#      workspace root still has a writable log rather than silently
#      writing into the repository.
APPROVAL_AUDIT_ENV = "GENESIS_APPROVAL_AUDIT_LOG"
APPROVAL_AUDIT_FILENAME = "approval_audit.jsonl"


def _audit_path() -> Path:
    """Resolve the audit log path. Never returns a path inside backend/.

    Raises RuntimeError if every candidate would land in the source
    tree: an audit log that modifies the thing it audits is worse than
    no audit log, so this fails loudly instead.
    """
    import os
    import tempfile

    from .workspace_boundary import (
        BoundaryConfigurationError,
        workspace_root,
    )

    backend_root = Path(__file__).resolve().parent.parent

    configured = os.environ.get(APPROVAL_AUDIT_ENV, "").strip()
    candidates = []
    if configured:
        explicit = Path(configured).expanduser()
        if explicit.is_dir():
            explicit = explicit / APPROVAL_AUDIT_FILENAME
        candidates.append(explicit)

    try:
        root = workspace_root()
    except BoundaryConfigurationError:
        root = None
    if root is not None:
        candidates.append(Path(root) / ".genesis_audit"
                          / APPROVAL_AUDIT_FILENAME)

    candidates.append(
        Path(tempfile.gettempdir()) / "genesis_audit"
        / APPROVAL_AUDIT_FILENAME)

    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(backend_root)
        except ValueError:
            return resolved
        continue

    raise RuntimeError(
        "every candidate audit-log location falls inside the source tree "
        f"({backend_root}); refusing to write the audit log into the thing "
        f"it audits. Set ${APPROVAL_AUDIT_ENV} to a path outside it."
    )


def append_audit(record: Mapping[str, Any]) -> None:
    """Append one decision record. Never stores arguments verbatim.

    Argument VALUES can contain file contents or a pasted secret, so only
    the argument names and a hash of the arguments are recorded. The
    resolved path is recorded because a human needs to know what they
    approved, and a path is not a secret.
    """
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "operation": record.get("operation"),
        "argument_names": sorted(record.get("argument_names") or []),
        "arguments_hash": record.get("arguments_hash"),
        "resolved_paths": list(record.get("resolved_paths") or []),
        "protected": bool(record.get("protected")),
        "protected_reason": record.get("protected_reason"),
        "decision": record.get("decision"),
        "channel": record.get("channel", "human-stdin"),
    }
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def read_audit() -> List[Dict[str, Any]]:
    """Read the audit log. Used by tests and by a future audit UI."""
    path = _audit_path()
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# The request object. Minted only from a hash-bound plan.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ApprovalRequest:
    """An approval ask derived from one specific plan.

    Frozen, and built from the plan's own fields. A caller cannot attach
    a friendly description to this and have it rendered -- property 2.
    """

    operation: str
    arguments: Mapping[str, Any]
    arguments_hash: str
    plan_target: Optional[str]
    tier: str
    blast_radius_reason: str
    resolved_paths: Sequence[str] = field(default_factory=tuple)
    outside_workspace: bool = False
    protected: bool = False
    protected_reason: Optional[str] = None

    def identity(self):
        """What single-use and argument-binding are checked against."""
        return (self.operation, self.arguments_hash)


def build_request(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    plan_target: Optional[str] = None,
) -> ApprovalRequest:
    """Derive an ApprovalRequest from a plan's canonical fields.

    Every field is computed here from the plan and the filesystem. There
    is no parameter through which a model or adapter could supply prompt
    text.
    """
    from genesis_os.blast_radius import resolve_blast_radius
    from genesis_os.workspace_boundary import _keys_for_capability

    # Only path-BEARING argument names are resolved. An earlier version
    # resolved every string value, so a `content` argument of "x" was
    # displayed as resolving to ".../backend/x" -- a factually wrong line
    # in a security prompt, and a string that happened to match a
    # protected prefix could be reported as a protected path.
    path_keys = _keys_for_capability(operation)

    resolved: List[str] = []
    protected_reason = None
    for name, value in arguments.items():
        if name not in path_keys:
            continue
        if not isinstance(value, str) or not value or "://" in value:
            continue
        try:
            candidate = Path(value).resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        resolved.append(str(candidate))
        if protected_reason is None:
            protected_reason = path_is_protected(candidate)

    tier_obj = resolve_blast_radius(operation, dict(arguments))
    reason = arguments_escape_workspace(dict(arguments))
    root = None
    try:
        root = workspace_root()
    except Exception:
        root = None

    from genesis_os.approval_store import _approval_arguments_hash

    return ApprovalRequest(
        operation=operation,
        arguments=dict(arguments),
        arguments_hash=_approval_arguments_hash(str(operation), dict(arguments)),
        plan_target=plan_target,
        tier=getattr(tier_obj, "value", str(tier_obj)),
        blast_radius_reason=(
            reason or f"blast radius {getattr(tier_obj, 'value', tier_obj)}"
        ),
        resolved_paths=tuple(resolved),
        outside_workspace=bool(reason),
        protected=bool(protected_reason),
        protected_reason=protected_reason,
    )


# ---------------------------------------------------------------------------
# Prompt rendering (property 2 and 3).
# ---------------------------------------------------------------------------
_PROTECTED_HEADER = (
    "PROTECTED PATH: this modifies Genesis's own safety logic or secrets"
)


def render_prompt(request: ApprovalRequest) -> str:
    """Fixed template. No caller-supplied prose can reach this."""
    lines: List[str] = []
    if request.protected:
        lines.append("!" * 68)
        lines.append(_PROTECTED_HEADER)
        if request.protected_reason:
            lines.append(f"  target: {request.protected_reason}")
        lines.append("!" * 68)
        lines.append("")
    lines.append("APPROVAL REQUIRED")
    lines.append(f"  operation : {request.operation}")
    if request.plan_target:
        lines.append(f"  target    : {request.plan_target}")
    for name in sorted(request.arguments):
        value = request.arguments[name]
        shown = value if isinstance(value, (int, float, bool)) else "<value>"
        lines.append(f"  argument  : {name} = {shown}")
    if request.resolved_paths:
        for path in request.resolved_paths:
            lines.append(f"  resolves to: {path}")
    lines.append(f"  tier      : {request.tier}")
    lines.append(f"  reason    : {request.blast_radius_reason}")
    if request.outside_workspace:
        lines.append("  note      : target is OUTSIDE the configured workspace")
    lines.append(f"  arguments hash: {request.arguments_hash}")
    if request.protected:
        lines.append("")
        lines.append(
            f"To approve, type exactly:  {PROTECTED_PHRASE}"
        )
    else:
        lines.append("To approve, type:  approve    (to deny, anything else)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The channel.
# ---------------------------------------------------------------------------
class ApprovalChannel:
    """Reads a human decision from the REPL's real stdin.

    Deliberately has NO auto-approve path. Every deny reason returns
    ``approved=False`` with a reason; there is no flag that turns a deny
    into an approve.
    """

    def __init__(
        self,
        stdin=None,
        stdout=None,
        *,
        timeout: float = 30.0,
        require_tty: bool = True,
    ):
        self._stdin = stdin
        self._stdout = stdout
        self.timeout = timeout
        self.require_tty = require_tty
        self._denied_in_turn: set = set()
        # request.identity() -> approval_id, recorded ONLY when a human
        # decision approved this exact operation+arguments. mint_grant
        # refuses anything absent from here.
        self._human_approved: Dict[tuple, str] = {}

    # -- property 5: discard buffered type-ahead before reading -----------
    def _discard_buffered_input(self) -> None:
        stream = self._stdin if self._stdin is not None else sys.stdin
        try:
            if stream is not None and stream.isatty():
                import termios

                termios.tcflush(stream, termios.TCIFLUSH)
        except Exception:
            # Non-tty, or termios unavailable (Windows console). Anything
            # already buffered is left alone; the read below still only
            # accepts an exact match.
            pass

    def _interactive(self) -> bool:
        """Property 4: no TTY means deny."""
        if not self.require_tty:
            return True
        stream = self._stdin if self._stdin is not None else sys.stdin
        if stream is None:
            return False
        try:
            return bool(stream.isatty())
        except Exception:
            return False

    # -- the prompt ------------------------------------------------------
    def request_approval(
        self,
        request: ApprovalRequest,
        *,
        turn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Show the prompt and return the human's decision.

        Never approves on anything except an exact phrase typed on the
        real stdin by a human.
        """
        # Property 7: no repeat prompt within a turn for the same thing.
        if turn_id is not None and request.identity() in self._denied_in_turn:
            return self._decide(
                request, False, "denied",
                channel="human-stdin",
                note="already denied in this turn; not re-prompting",
            )

        if not self._interactive():
            return self._decide(
                request, False, "denied",
                channel="human-stdin",
                note="non-interactive context (no TTY); denying by default",
            )

        out = self._stdout if self._stdout is not None else sys.stdout
        print(render_prompt(request), file=out, flush=True)

        self._discard_buffered_input()

        try:
            answer = self._read_line()
        except EOFError:
            return self._decide(
                request, False, "denied", channel="human-stdin",
                note="stdin reached EOF",
            )
        except TimeoutError:
            return self._decide(
                request, False, "denied", channel="human-stdin",
                note="timed out waiting for a human decision",
            )
        if answer is None:
            return self._decide(
                request, False, "denied", channel="human-stdin",
                note="stdin closed",
            )

        answer = answer.strip()
        if request.protected:
            approved = answer == PROTECTED_PHRASE
            expected = PROTECTED_PHRASE
        else:
            approved = answer.lower() == "approve"
            expected = "approve"

        if not approved:
            if turn_id is not None:
                self._denied_in_turn.add(request.identity())
            return self._decide(
                request, False, "denied", channel="human-stdin",
                note=f"expected {expected!r}, got {answer[:40]!r}",
            )

        # A real human approved THIS exact operation+arguments. Persist
        # that decision so mint_grant can consume it rather than
        # manufacturing one.
        self._record_human_approval(request)
        return self._decide(request, True, "approved", channel="human-stdin")

    def _record_human_approval(self, request: ApprovalRequest) -> str:
        """Persist the human decision in ApprovalStore.

        This is the ONE sanctioned call to ``ApprovalStore.approve()``
        (property 1). It runs only on the branch where a real human
        typed the exact expected phrase, and only after the channel has
        read and matched that phrase.

        Previously nothing was recorded here: ``mint_grant`` created and
        approved its own record, so the human decision was not what made
        the approval -- mint_grant was. Recording it here means the
        store, not the caller, is the source of truth about whether an
        approval exists.
        """
        store = ApprovalStore.get_default()
        record = store.request(request.operation, dict(request.arguments))
        approval_id = record["approval_id"]
        store.approve(approval_id, approver="human")
        self._human_approved[request.identity()] = approval_id
        return approval_id

    def _read_line(self) -> Optional[str]:
        stream = self._stdin if self._stdin is not None else sys.stdin
        if stream is None:
            return None
        if self.timeout:
            return self._read_line_bounded(stream, self.timeout)
        line = stream.readline()
        if line == "":
            raise EOFError("human decision stream closed")
        return line

    # ---------------------------------------------------------------
    # Item 15B (S13): the approval channel was DEAD on Windows.
    # ---------------------------------------------------------------
    #
    # The bounded read used select.select([stream], [], [], timeout).
    # On Windows, select() supports SOCKETS ONLY -- passing a file
    # handle raises OSError [WinError 10093] ("WSAStartup has not been
    # called"). That is not an edge case: it is every console on the
    # platform. Measured on a real Windows console with isatty() True:
    #
    #     select.select([sys.stdin], [], [], 1.0)
    #     -> OSError: [WinError 10093]
    #
    # The old handler caught that OSError and raised TimeoutError, which
    # request_approval maps to `denied`. So on Windows a human could
    # NEVER approve anything: a genuine interactive console produced
    # exactly the same result as a closed pipe, and every Tier 1 action
    # was unapprovable by construction. The system was safe and
    # completely inert -- the failure was invisible precisely because
    # it looked like correct fail-closed behaviour.
    #
    # A reader thread with join(timeout) bounds the wait on every
    # platform, including win32, and works with an INJECTED stream --
    # which msvcrt console polling would not, since msvcrt can only
    # reach the process's real console.
    #
    # HONEST LIMIT, not papered over: if the join times out, the worker
    # is still blocked inside readline() and is abandoned (daemon; it
    # dies with the process). Nothing unblocks it. The practical
    # consequence is that a keystroke typed after a timeout may be
    # swallowed by that zombie thread instead of reaching the next
    # prompt. That is a fairness wart, not a safety one -- we have
    # already DENIED, so no operation proceeds on the abandoned read.
    #
    # Fail-closed is preserved where it matters:
    #   * a stream that is not a TTY is denied earlier, by
    #     _interactive() (property 4), which runs before this;
    #   * no answer within the timeout is a denial;
    #   * a read that raises is a denial, never an approval;
    #   * EOF is a denial.
    def _read_line_bounded(
        self, stream: Any, timeout: float
    ) -> str:
        box: Dict[str, Any] = {}

        def _worker() -> None:
            try:
                box["line"] = stream.readline()
            except Exception as exc:
                # Captured, not raised: this runs off the main thread,
                # so an escaping exception would only kill the worker
                # and leave join() to guess. The caller decides.
                #
                # `Exception`, not `BaseException`: a KeyboardInterrupt
                # belongs to the MAIN thread and must not be swallowed
                # here, and if the worker somehow dies without setting
                # `line` the empty-string branch below raises EOFError,
                # which denies -- so nothing escapes as consent.
                box["error"] = exc

        worker = threading.Thread(
            target=_worker,
            daemon=True,
            name="genesis-approval-read",
        )
        worker.start()
        worker.join(timeout)

        if worker.is_alive():
            raise TimeoutError("human decision timed out")

        error = box.get("error")
        if error is not None:
            if isinstance(error, EOFError):
                raise error
            # Anything else went wrong reading a stream we believed was
            # interactive. Deny; never treat a broken read as consent.
            raise TimeoutError(
                f"approval read failed: {error}"
            )

        line = box.get("line", "")
        if line == "":
            raise EOFError("human decision stream closed")
        return line

    def _decide(
        self,
        request: ApprovalRequest,
        approved: bool,
        decision: str,
        *,
        channel: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        append_audit(
            {
                "operation": request.operation,
                "argument_names": sorted(request.arguments),
                "arguments_hash": request.arguments_hash,
                "resolved_paths": list(request.resolved_paths),
                "protected": request.protected,
                "protected_reason": request.protected_reason,
                "decision": decision,
                "channel": channel,
            }
        )
        return {
            "approved": approved,
            "decision": decision,
            "channel": channel,
            "note": note,
        }

    def mint_grant(self, request: ApprovalRequest) -> Any:
        """Mint the grant for a request a HUMAN ALREADY APPROVED.

        Property 1: only a human decision may approve. Property 6: the
        grant is single-use and bound to the exact arguments hash, so
        approving A cannot authorize B.

        DESIGN NOTE (2026-10-15) -- why this is not `issue` + `approve`:

        The previous implementation called
        ``ApprovalStore.issue_token(...)`` and then
        ``ApprovalStore.get_default().approve(...)`` ITSELF. That made
        the human decision structurally optional: the module approved on
        its own behalf, so the very call that was supposed to require a
        human supplied the approval. It also contradicted this module's
        own property 1, which names a single sanctioned caller of
        ``ApprovalStore.approve()``.

        So the approval must already EXIST and must already be APPROVED,
        recorded by this channel when a human typed the expected phrase.
        This method CONSUMES that record and mints from the consumption
        (via ``grant_from_consumed_record``, which re-checks the binding).
        If no approved record matches this exact operation and arguments
        hash, it raises rather than manufacturing one.

        Consuming the human's own record -- rather than issuing a fresh
        token -- is what makes the approval structural: the token's nonce
        IS that record's approval_id, so there is exactly one approval
        per grant and it can be spent only once.
        """
        store = ApprovalStore.get_default()
        approval_id = self._human_approved.get(request.identity())
        record = store.status(approval_id) if approval_id else None
        if (record is None
                or record.get("status") != "approved"
                or str(record.get("capability_id")) != str(request.operation)
                or record.get("arguments_hash") != request.arguments_hash):
            raise RuntimeError(
                "refusing to mint a grant: no HUMAN-APPROVED approval record "
                f"exists for {request.operation!r} with arguments hash "
                f"{request.arguments_hash[:16]}... A human must approve the "
                "request through this channel before a grant can be minted."
            )

        # Spend the human's own approval. The token nonce is that
        # approval_id, so consume_token verifies and consumes THAT record.
        token = f"HUMAN-APPROVE:{request.operation}:{approval_id}"
        consumed = store.consume_token(
            token, arguments=dict(request.arguments)
        )
        self._human_approved.pop(request.identity(), None)
        from genesis_os.authorization_grant import grant_from_consumed_record

        return grant_from_consumed_record(
            operation=request.operation,
            arguments=dict(request.arguments),
            record=consumed,
        )