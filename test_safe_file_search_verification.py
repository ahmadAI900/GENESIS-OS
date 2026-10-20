"""Item 22A (C22): search verification was a copy of the success flag.

SafeFileManager.search (explicit-root path) did:

    result["verified"] = bool(result.get("success"))
    result["post_state_matches"] = result["verified"]
    result["verification_type"] = "lexical_search_completed"

The FileManager walk completed -> success=True -> verified=True,
regardless of what the result actually claimed. verified was never
an observation: a search reporting a match that is not on disk
(silent no-op, stale cache, fabricated entry) still claimed
verified=True, and a search reporting ZERO matches claimed it too.

Every other verified path in this module READS THE STATE BACK
(create compares re-read content, delete checks the target is gone,
copy/move hash-compare). The explicit-root search did not: it
verified the walk, not the claim.

REPRODUCED, not assumed, against the committed original:

    stub manager.search -> success=True, matches=[<missing path>]
    result["verified"] -> True   <- the match does not exist

The fix reads the observation back: each reported match is checked
on disk. verified reflects what was observed (all reported matches
exist; at least one match was observed), never the success flag --
consistent with the semantic-search branch, where verified is
already bool(ranked_paths).
"""
from __future__ import annotations

from pathlib import Path

from genesis_os.safe_file_manager import SafeFileManager


class _LyingSearchManager:
    """Claims a walk completed and reports matches that need not exist."""

    def __init__(self, matches, success=True):
        self._matches = list(matches)
        self._success = success

    def search(self, root, query, *args, **kwargs):
        return {
            "success": self._success,
            "operation": "file.search",
            "root": str(root),
            "query": str(query).lower(),
            "matches": list(self._matches),
            "count": len(self._matches),
        }


# --------------------------------------------------------------------------
# The regression: a claim that is not on disk must not be "verified"
# --------------------------------------------------------------------------

def test_a_search_reporting_a_missing_match_is_not_verified(tmp_path):
    ghost = tmp_path / "ghost_match.txt"  # deliberately never created
    manager = _LyingSearchManager([str(ghost)])

    result = SafeFileManager(manager=manager).search(
        str(tmp_path), "ghost"
    )

    assert result["success"] is True, "the walk itself completed"
    assert result["verified"] is False, (
        "a search that reported a match which is not on disk claims "
        "verified=True -- verified was just bool(success), never an "
        "observation of the claim"
    )


def test_success_with_no_observed_match_is_not_verified(tmp_path):
    manager = _LyingSearchManager([])

    result = SafeFileManager(manager=manager).search(
        str(tmp_path), "anything"
    )

    assert result["success"] is True
    assert result["verified"] is False, (
        "an empty result claims verified=True off the success flag; "
        "nothing was observed, so nothing is verified (the semantic "
        "branch already treats an empty result as unverified)"
    )


def test_one_real_and_one_missing_match_is_not_verified(tmp_path):
    real = tmp_path / "real_note.txt"
    real.write_text("x", encoding="utf-8")
    ghost = tmp_path / "ghost_note.txt"
    manager = _LyingSearchManager([str(real), str(ghost)])

    result = SafeFileManager(manager=manager).search(
        str(tmp_path), "note"
    )

    assert result.get("matches_verified") == 1, result
    assert result["verified"] is False, (
        "a result claiming two matches while only one exists was "
        "still verified -- the claim as a whole must be observed, "
        "not sampled"
    )


# --------------------------------------------------------------------------
# The honest side: a real observed match verifies; a failure never does
# --------------------------------------------------------------------------

def test_a_real_search_of_an_existing_file_is_verified(tmp_path):
    target = tmp_path / "quarterly_report.txt"
    target.write_text("numbers", encoding="utf-8")

    # Real FileManager on real disk: the read-back is the disk itself.
    result = SafeFileManager().search(str(tmp_path), "quarterly_report")

    assert result["success"] is True, result
    assert str(target) in result["matches"], result
    assert result["verified"] is True, (
        f"a genuine match on disk must verify: {result}"
    )
    assert result["post_state_matches"] is True


def test_a_failed_walk_is_never_verified(tmp_path):
    manager = _LyingSearchManager([str(tmp_path / "x")], success=False)

    result = SafeFileManager(manager=manager).search(
        str(tmp_path), "x"
    )

    assert result["success"] is False
    assert result["verified"] is False


def test_the_verification_says_what_was_checked(tmp_path):
    manager = _LyingSearchManager([])

    result = SafeFileManager(manager=manager).search(
        str(tmp_path), "anything"
    )

    assert "lexical_search_completed" not in str(
        result.get("verification_type", "")
    ), (
        "the verification type still claims the walk was the "
        "verification; it must say the matches were checked on disk"
    )
