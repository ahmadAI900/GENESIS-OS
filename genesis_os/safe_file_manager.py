"""Genesis OS — Safe file execution gateway (Level 3.7+)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from .filesystem.file_manager import FileManager
from .file_intelligence.file_service import FileIntelligenceService
from .file_intelligence.path_security import PathSecurity


class SafeFileManager:
    """Compatibility wrapper around the existing FileManager.

    The legacy FileManager remains intact. This gateway adds path validation,
    deterministic result contracts and confirmation requirements for
    destructive/overwriting operations.
    """

    VERSION = "3.8.0"

    def __init__(self, manager: FileManager | None = None):
        self.manager = manager or FileManager()
        self.intelligence = FileIntelligenceService()

    @staticmethod
    def _validate(path: Any, *, existing=False, file=False, directory=False):
        return PathSecurity.validate(
            path,
            require_existing=existing,
            require_file=file,
            require_directory=directory,
        )

    def inspect(self, path: Any) -> dict:
        result = self.intelligence.inspect(path)
        return self._result_dict(result, "file.inspect")

    def read(self, path: Any) -> dict:
        validation = self._validate(path, existing=True, file=True)
        if not validation["allowed"]:
            return self._failure("file.read", validation)
        result = self.manager.read_text(validation["path"])
        if isinstance(result, dict):
            result["operation"] = "file.read"
            result["path"] = validation["path"]
            result["file_type"] = self._file_type(validation["path"])
            result["file_exists"] = Path(validation["path"]).is_file()
            result["verified"] = bool(
                result.get("success")
                and result["file_exists"]
                and isinstance(result.get("content"), str)
            )
            result["post_state_matches"] = result["verified"]
        return result

    # Roots searched when the caller does not name a concrete
    # location. Semantic requests such as "find my IELTS essay"
    # have no literal path, so Genesis searches the standard
    # user locations instead of only the working directory.
    SEMANTIC_SEARCH_ROOT_MARKERS = frozenset({
        "",
        ".",
        "computer",
        "files",
        "filesystem",
        "my files",
        "my computer",
    })

    def _semantic_search_roots(self):
        roots = []
        candidates = [Path.cwd()]
        home = Path.home()
        candidates.extend([
            home / "Downloads",
            home / "Documents",
            home / "Desktop",
        ])
        for candidate in candidates:
            validation = self._validate(str(candidate), existing=True, directory=True)
            if not validation["allowed"]:
                continue
            resolved = Path(validation["path"])
            if resolved.is_dir() and resolved not in roots:
                roots.append(resolved)
        return roots

    def search(self, path: Any = None, query: str = "") -> dict:
        marker = "" if path is None else str(path).strip().lower()
        explicit_root = marker not in self.SEMANTIC_SEARCH_ROOT_MARKERS

        if explicit_root:
            validation = self._validate(path, existing=True)
            if not validation["allowed"]:
                return self._failure("file.search", validation)
            result = self.manager.search(validation["path"], query)
            if isinstance(result, dict):
                # Item 22A (C22): verified used to be
                # bool(result.get("success")) -- the walk completed,
                # so the result was declared verified. That verified
                # the walk, not the CLAIM: a match that is not on
                # disk (silent no-op, stale entry) still claimed
                # verified=True, and so did a zero-match result.
                # Read the observation back instead, the way every
                # other verified path in this module does (create
                # re-reads content, delete checks the target is
                # gone, copy/move hash-compare): each reported match
                # is checked on disk, and verified reflects what was
                # observed -- never the success flag. The semantic
                # multi-root branch below already treated an empty
                # result as unverified; the two now agree.
                matches = result.get("matches")
                if not isinstance(matches, list):
                    matches = []
                matches_verified = sum(
                    1 for match in matches
                    if Path(match).is_file()
                )
                result["matches_verified"] = matches_verified
                result["verified"] = bool(
                    result.get("success")
                    and matches
                    and matches_verified == len(matches)
                )
                result["post_state_matches"] = result["verified"]
                result["verification_type"] = (
                    "reported_matches_exist_on_disk"
                )
            return result

        # -----------------------------------------------------
        # SEMANTIC MULTI-ROOT SEARCH
        #
        # No concrete location was requested. Search the
        # standard user locations and rank matches so that
        # natural-language file requests genuinely find files.
        # -----------------------------------------------------

        if not isinstance(query, str) or not query.strip():
            return {"success": False, "operation": "file.search", "error": "Search query is required."}

        query_text = query.strip()
        query_lower = query_text.lower()
        terms = [t for t in query_lower.replace("_", " ").replace("-", " ").replace(".", " ").split() if t]

        roots = self._semantic_search_roots()

        if not roots:
            return {
                "success": False,
                "operation": "file.search",
                "error": "No accessible filesystem location was available to search.",
                "executed": False,
                "verified": False,
            }

        max_results = 100
        scored: dict[str, tuple[float, str]] = {}

        for root in roots:
            try:
                iterator = root.rglob("*")
                for item in iterator:
                    try:
                        if not item.is_file():
                            continue
                    except OSError:
                        continue

                    name_lower = item.name.lower()
                    stem_lower = item.stem.lower()

                    if query_lower in name_lower or query_lower in stem_lower:
                        score = 0.95
                    elif terms and all(term in name_lower or term in stem_lower for term in terms):
                        score = 0.85
                    elif terms:
                        matched = sum(1 for term in terms if term in name_lower or term in stem_lower)
                        if not matched:
                            continue
                        score = 0.40 + (0.30 * matched / len(terms))
                    else:
                        continue

                    item_str = str(item)
                    existing = scored.get(item_str)
                    if existing is None or score > existing[0]:
                        scored[item_str] = (score, item_str)

                    if len(scored) >= max_results * 4:
                        break
            except OSError:
                continue

        ranked_entries = sorted(
            scored.values(),
            key=lambda entry: (-entry[0], entry[1].casefold()),
        )

        ranked_paths = [
            path_str
            for _, path_str in ranked_entries
        ][:max_results]

        return {
"success": bool(ranked_paths),
            "operation": "file.search",
            "root": str(roots[0]),
            "roots": [str(root) for root in roots],
            "query": query_text,
            "matches": ranked_paths,
            "count": len(ranked_paths),
            "executed": False,
            "verified": bool(ranked_paths),
            "verification_type": "lexical_filename_match",
            "verification_reason": (
                "At least one filename matched."
                if ranked_paths
                else "No filename matched the lexical query."
            ),
        }

    def open(self, path: Any) -> dict:
        validation = self._validate(path, existing=True, file=True)
        if not validation["allowed"]:
            return self._failure("file.open", validation)
        return self.manager.open(validation["path"])

    def hash(self, path: Any, algorithm: str = "sha256") -> dict:
        validation = self._validate(path, existing=True, file=True)
        if not validation["allowed"]:
            return self._failure("file.hash", validation)
        return self.manager.hash(validation["path"], algorithm=algorithm)

    def create(self, path: Any, content: str = "", *, overwrite=False) -> dict:
        # Item 7C: the vestigial `confirmed=False` parameter is GONE. It
        # was never an authority (Item 3B-3b removed that channel), so
        # keeping it only let `confirmed=True` travel silently through
        # OSManager's **kwargs and suggest a bypass that does not exist.
        # Overwriting an existing file is Tier 1 at the executor's
        # blast-radius gate (Item 3B-3a) and requires a valid
        # AuthorizationGrant BEFORE this method is reached; a create onto
        # a free path is Tier 2. The `overwrite` flag still decides
        # whether an existing target is clobbered, but it no longer has to
        # be paired with a confirmation to be allowed through.
        validation = self._validate(path)
        if not validation["allowed"]:
            return self._failure("file.create", validation)
        target = Path(validation["path"])
        if target.exists() and not overwrite:
            return {"success": False, "operation": "file.create", "status": "already_exists",
                    "path": str(target), "message": "The destination already exists."}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            expected = str(content)
            target.write_text(expected, encoding="utf-8")
            content_matches = target.is_file() and target.read_text(encoding="utf-8") == expected
            return {"success": content_matches, "operation": "file.create", "path": str(target),
                    "message": f"Created {target.name}.", "executed": True,
                    "verified": content_matches, "file_exists": target.is_file(),
                    "content_match": content_matches,
                    "post_state_matches": content_matches}
        except OSError as exc:
            return {"success": False, "operation": "file.create", "path": str(target),
                    "error": str(exc), "message": "Genesis could not create the file."}

    def copy(self, source: Any, destination: Any) -> dict:
        return self._mutate("file.copy", source, destination, self.manager.copy, overwrite=True)

    def move(self, source: Any, destination: Any) -> dict:
        return self._mutate("file.move", source, destination, self.manager.move, overwrite=True)

    def rename(self, source: Any, new_name: str) -> dict:
        # Item 7C: vestigial `confirmed` parameter removed; it was never
        # an authority. See create().
        # Renaming ONTO an existing file is Tier 1 at the executor gate;
        # a rename to a free name is Tier 2 and proceeds.
        validation = self._validate(source, existing=True, file=True)
        if not validation["allowed"]:
            return self._failure("file.rename", validation)
        if not isinstance(new_name, str) or not new_name.strip() or Path(new_name).name != new_name:
            return {"success": False, "operation": "file.rename", "error": "A safe file name is required."}
        target = Path(validation["path"]).parent / new_name.strip()
        result = self.manager.rename(validation["path"], new_name.strip())
        old_path = Path(validation["path"])
        new_path = Path(result.get("new_path", target)) if isinstance(result, dict) else target
        verified = bool(
            isinstance(result, dict)
            and result.get("success")
            and new_path.is_file()
            and not old_path.exists()
        )
        if isinstance(result, dict):
            result["executed"] = bool(result.get("success"))
            result["verified"] = verified
            result["old_path_exists"] = old_path.exists()
            result["destination_exists"] = new_path.is_file()
            result["post_state_matches"] = verified
        return result

    def delete(self, path: Any) -> dict:
        # Item 7C: vestigial `confirmed` parameter removed; it was never
        # an authority. See create().
        # file.delete is Tier 1 at the executor gate, so reaching here
        # already required a valid AuthorizationGrant.
        validation = self._validate(path, existing=True, file=True)
        if not validation["allowed"]:
            return self._failure("file.delete", validation)
        target = Path(validation["path"])
        result = self.manager.delete(target, confirm=True)
        verified = bool(
            result.get("success")
            and not target.exists()
        )
        result["executed"] = bool(result.get("success"))
        result["verified"] = verified
        result["file_exists"] = target.exists()
        result["post_state_matches"] = verified
        return result

    @staticmethod
    def _files_match(left: Path, right: Path) -> bool:
        if not left.is_file() or not right.is_file():
            return False
        if left.stat().st_size != right.stat().st_size:
            return False
        digests = []
        for path in (left, right):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digests.append(digest.digest())
        return digests[0] == digests[1]

    def _mutate(self, operation, source, destination, fn, *, overwrite=False):
        # Item 7C: the vestigial `confirmed` parameter is removed from
        # this sink too. It was forwarded faithfully by copy()/move() and
        # then ignored here, so the whole chain carried a parameter that
        # never influenced anything. See create().
        # Overwriting an existing destination is Tier 1 at the executor
        # gate (Item 3B-3a); a free destination is Tier 2 and proceeds.
        src = self._validate(source, existing=True, file=True)
        if not src["allowed"]:
            return self._failure(operation, src)
        dst = self._validate(destination)
        if not dst["allowed"]:
            return self._failure(operation, dst)
        target = Path(dst["path"])
        try:
            result = fn(src["path"], str(target))
            source_path = Path(src["path"])
            destination_exists = target.is_file()
            source_removed = not source_path.exists()
            file_matches = self._files_match(source_path, target) if operation == "file.copy" else None
            if operation == "file.copy":
                verified = bool(
                    result.get("success")
                    and destination_exists
                    and file_matches
                )
            else:
                verified = bool(
                    result.get("success")
                    and destination_exists
                    and source_removed
                )
            result["executed"] = bool(result.get("success"))
            result["verified"] = verified
            result["destination_exists"] = destination_exists
            result["source_removed"] = source_removed
            if operation == "file.copy":
                result["file_matches"] = bool(file_matches)
            result["post_state_matches"] = verified
            return result
        except Exception as exc:
            return {"success": False, "operation": operation, "error": str(exc), "executed": False, "verified": False}

    def _file_type(self, path):
        return self.intelligence.inspect(path).metadata.get("file_type", "unknown")

    @staticmethod
    def _result_dict(result, operation):
        if hasattr(result, "to_dict"):
            data = result.to_dict()
        else:
            data = dict(result)
        data["operation"] = operation
        data["executed"] = False
        identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
        file_exists = bool(identity.get("exists"))
        verified = bool(data.get("success") and file_exists)
        data["file_exists"] = file_exists
        data["verified"] = verified
        data["post_state_matches"] = verified
        return data

    @staticmethod
    def _failure(operation, validation):
        return {"success": False, "operation": operation, "path": validation.get("path"),
                "error": validation.get("reason"), "message": validation.get("reason"),
                "executed": False, "verified": False}
