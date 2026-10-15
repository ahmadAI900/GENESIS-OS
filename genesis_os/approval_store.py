"""
Genesis OS - HIL Approval Queue
================================

Phase 2/13 groundwork: honest programmatic human-in-the-loop (HIL).

This module is a small, stdlib-only approval queue.  When the
``AgentFrameworkAdapter`` bounces a destructive capability with a
structured ``confirmation_required`` result (executor NOT called),
it auto-creates a pending entry here and attaches the entry's
``approval_id`` to the result metadata.  A human UI (or test
harness) can then approve/reject the entry out-of-band.

Token contract (unchanged, shared with
``agent_framework_adapter.py``)::

    HUMAN-APPROVE:<capability_id>:<nonce>

``ApprovalStore.issue_token`` creates a queue entry AND returns a
token whose nonce equals the entry's ``approval_id``, so every
token is traceable to exactly one queue entry.
``consume_token`` requires an explicitly approved queue entry and
binds the token to the canonical operation arguments; tokens are
single-use.

Thread-safety: all state mutations are guarded by
``threading.Lock``.  No third-party dependencies.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional


APPROVAL_TOKEN_PREFIX = "HUMAN-APPROVE:"

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
CONSUMED = "consumed"


class _Record(dict):
    """Result record with a convenience equality against status.

    Behaves exactly like a ``dict`` (``record["status"]``,
    ``record["approval_id"]``, JSON-serializable) and additionally
    compares equal to its status string, so both of these hold::

        store.status(approval_id) == "pending"
        store.status(approval_id)["status"] == "pending"
    """

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.get("status") == other
        return super().__eq__(other)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_token(token: Any) -> tuple:
    """Split ``HUMAN-APPROVE:<capability_id>:<nonce>``.

    Returns ``(capability_id, nonce)``.  Raises ``ValueError``
    when the format is invalid (bad prefix, missing parts, or
    nonce shorter than 4 chars after stripping).
    """
    if not isinstance(token, str):
        raise ValueError(f"invalid approval token: {token!r}")
    if not token.startswith(APPROVAL_TOKEN_PREFIX):
        raise ValueError(
            f"invalid approval token (missing "
            f"{APPROVAL_TOKEN_PREFIX!r} prefix): {token!r}"
        )
    remainder = token[len(APPROVAL_TOKEN_PREFIX):]
    if ":" not in remainder:
        raise ValueError(
            f"invalid approval token (expected "
            f"'HUMAN-APPROVE:<capability_id>:<nonce>'): {token!r}"
        )
    # Capability ids contain a dot but never a colon, so split
    # on the LAST colon to allow nonces that contain colons.
    cap_part, _, nonce = remainder.rpartition(":")
    cap_part = cap_part.strip()
    nonce = nonce.strip()
    if not cap_part:
        raise ValueError(
            f"invalid approval token (empty capability_id): "
            f"{token!r}"
        )
    if len(nonce) < 4:
        raise ValueError(
            f"invalid approval token (nonce must be >= 4 "
            f"chars): {token!r}"
        )
    return cap_part, nonce


_APPROVAL_CONTROL_KEYS = frozenset({
    "approval_id",
    "approval_token",
    "confirmed",
    "provider",
})
_PATH_KEYS = frozenset({
    "path",
    "source",
    "destination",
    "output",
    "output_path",
    "save_path",
    "file_path",
    "directory",
    "folder",
    "new_name",
    "target",
})


def _canonicalize_approval_value(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(item_key): _canonicalize_approval_value(
                item_value,
                str(item_key),
            )
            for item_key, item_value in sorted(
                value.items(),
                key=lambda item: str(item[0]),
            )
            if str(item_key).lower() not in _APPROVAL_CONTROL_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [
            _canonicalize_approval_value(item, key)
            for item in value
        ]
    if (
        key.lower() in _PATH_KEYS
        and isinstance(value, (str, os.PathLike))
    ):
        text = os.fspath(value)
        if "://" not in text:
            return os.path.normcase(
                os.path.abspath(os.path.expanduser(text))
            )
    return value


def _approval_arguments_hash(
    capability_id: str,
    arguments: Optional[Mapping[str, Any]],
) -> str:
    canonical = {
        "capability_id": str(capability_id),
        "arguments": _canonicalize_approval_value(
            dict(arguments or {})
        ),
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ApprovalStore:
    """Thread-safe in-memory HIL approval queue (stdlib only).

    Instance API::

        store = ApprovalStore()
        rec = store.request("file.delete", {"path": "C:/t.txt"})
        # -> {"approval_id": "APR-...-0001", "status": "pending", ...}
        store.approve(rec["approval_id"])
        store.status(rec["approval_id"])   # -> {"status": "approved", ...}
        store.pending()                    # -> [pending records]

    Traceable-token API (class level, shared default queue)::

        token = ApprovalStore.issue_token("file.delete")
        # -> "HUMAN-APPROVE:file.delete:APR-...-0001"
        ApprovalStore.get_default().approve(
            token.rsplit(":", 1)[1]
        )
        ApprovalStore.consume_token(
            token,
            arguments={"path": "C:/t.txt"},
        )
    """

    _shared_lock = threading.Lock()
    _id_lock = threading.Lock()
    _id_counter = 0
    _default: Optional["ApprovalStore"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Dict[str, Dict[str, Any]] = {}

    # --------------------------------------------------------
    # SHARED DEFAULT QUEUE (used by the class-level token API
    # and by the adapter's lazy wiring)
    # --------------------------------------------------------

    @classmethod
    def get_default(cls) -> "ApprovalStore":
        """Return the process-wide shared store (lazy singleton)."""
        instance = cls._default
        if instance is None:
            with cls._shared_lock:
                if cls._default is None:
                    cls._default = cls()
                instance = cls._default
        return instance

    # --------------------------------------------------------
    # CORE QUEUE API
    # --------------------------------------------------------

    def request(
        self,
        capability_id: str,
        arguments: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a pending approval request.

        Returns ``{"approval_id": "APR-<utc-timestamp>-<counter>",
        "capability_id": ..., "status": "pending", ...}``.
        """
        if not isinstance(capability_id, str) or not (
            capability_id.strip()
        ):
            raise ValueError(
                "capability_id must be a non-empty string"
            )
        capability_id = capability_id.strip()
        if arguments is None:
            args_snapshot: Dict[str, Any] = {}
        else:
            try:
                args_snapshot = copy.deepcopy(dict(arguments))
            except Exception:
                args_snapshot = {
                    "_unserializable_arguments": True
                }
        # The counter is process-wide (not per-instance) so ids are
        # unique across all stores even within the same second.
        with ApprovalStore._id_lock:
            ApprovalStore._id_counter += 1
            counter = ApprovalStore._id_counter
        approval_id = f"APR-{_utc_stamp()}-{counter:04d}"
        with self._lock:
            record = {
                "approval_id": approval_id,
                "capability_id": capability_id,
                "arguments": args_snapshot,
                "arguments_hash": _approval_arguments_hash(
                    capability_id,
                    args_snapshot,
                ),
                "status": PENDING,
                "approver": None,
                "reason": "",
                "created_at": _utc_now_iso(),
                "resolved_at": None,
            }
            self._requests[approval_id] = record
            return _Record(copy.deepcopy(record))

    def approve(
        self,
        approval_id: str,
        approver: str = "human",
    ) -> Dict[str, Any]:
        """Mark ``approval_id`` approved.  Raises ``KeyError``."""
        with self._lock:
            record = self._requests.get(approval_id)
            if record is None:
                raise KeyError(
                    f"unknown approval_id: {approval_id!r}"
                )
            record["status"] = APPROVED
            record["approver"] = approver
            record["resolved_at"] = _utc_now_iso()
            return _Record(copy.deepcopy(record))

    def reject(
        self,
        approval_id: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Mark ``approval_id`` rejected.  Raises ``KeyError``."""
        with self._lock:
            record = self._requests.get(approval_id)
            if record is None:
                raise KeyError(
                    f"unknown approval_id: {approval_id!r}"
                )
            record["status"] = REJECTED
            record["reason"] = reason
            record["resolved_at"] = _utc_now_iso()
            return _Record(copy.deepcopy(record))

    def status(
        self, approval_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the record for ``approval_id`` (or ``None``)."""
        with self._lock:
            record = self._requests.get(approval_id)
            if record is None:
                return None
            return _Record(copy.deepcopy(record))

    def pending(self) -> List[Dict[str, Any]]:
        """Return all records whose status is still ``pending``."""
        with self._lock:
            return [
                _Record(copy.deepcopy(record))
                for record in self._requests.values()
                if record.get("status") == PENDING
            ]

    # --------------------------------------------------------
    # TRACEABLE-TOKEN API
    # --------------------------------------------------------

    @classmethod
    def issue_token(
        cls,
        capability_id: str,
        arguments: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Create a pending request AND return its approval token.

        The token nonce equals the queue entry's ``approval_id``::

            "HUMAN-APPROVE:<capability_id>:<approval_id>"

        so every token is traceable to exactly one queue entry.
        Entries live on the shared default queue (see
        ``get_default``).
        """
        store = cls.get_default()
        record = store.request(
            capability_id,
            dict(arguments) if arguments is not None else {},
        )
        return (
            f"{APPROVAL_TOKEN_PREFIX}"
            f"{record['capability_id']}:{record['approval_id']}"
        )

    def consume_token(
        first: Any,
        second: Any = None,
        *,
        arguments: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Consume an explicitly approved, argument-bound token.

        May be called either on the class or on an instance::

            ApprovalStore.consume_token(token, arguments=args)
            store.consume_token(token, arguments=args)

        The request must already be approved by a human. The
        canonical argument hash must match the request that was
        approved.
        """
        if isinstance(first, ApprovalStore):
            instance = first
            token = second
            search_default_fallback = True
        elif isinstance(first, str):
            instance = None
            token = first
            search_default_fallback = False
        else:
            raise ValueError(
                f"invalid approval token: {first!r}"
            )

        capability_id, nonce = _parse_token(token)
        if not isinstance(arguments, Mapping):
            raise ValueError(
                "approval arguments are required to consume a token"
            )
        incoming_hash = _approval_arguments_hash(
            capability_id,
            arguments,
        )

        candidates: List["ApprovalStore"] = []
        if instance is not None:
            candidates.append(instance)
            if search_default_fallback:
                candidates.append(ApprovalStore.get_default())
        else:
            candidates.append(ApprovalStore.get_default())

        seen = set()
        for store in candidates:
            if id(store) in seen:
                continue
            seen.add(id(store))
            with store._lock:
                record = store._requests.get(nonce)
                if record is None:
                    continue
                if record.get("capability_id") != capability_id:
                    raise ValueError(
                        f"approval token capability "
                        f"{capability_id!r} does not match queued "
                        f"request "
                        f"{record.get('capability_id')!r} for "
                        f"{nonce!r}"
                    )
                if record.get("status") == PENDING:
                    raise ValueError(
                        f"approval {nonce!r} is pending human approval"
                    )
                if record.get("status") != APPROVED:
                    raise ValueError(
                        f"approval {nonce!r} is not approved "
                        f"(status={record.get('status')!r})"
                    )
                if record.get("arguments_hash") != incoming_hash:
                    raise ValueError(
                        f"approval arguments do not match the approved "
                        f"request for {capability_id!r}"
                    )
                record["status"] = CONSUMED
                record["approver"] = record.get("approver") or "token"
                record["resolved_at"] = _utc_now_iso()
                return _Record(copy.deepcopy(record))

        raise ValueError(
            f"approval token matches no queued request: "
            f"{token!r}"
        )
