"""
Genesis OS — Level 3.8.5
File Target Provider.

Adapter connecting FileIntelligenceService and filesystem search
to the Level 3.8.4 TargetResolver.

This layer performs read-only target candidate discovery.
It NEVER modifies or deletes files.

Level 3.8.5 enhancements:
- Semantic query parsing for recency/type/location preferences
- Recency-first sorting when "newest"/"latest" is specified
- Location-hint narrowed search roots
- Extension from semantic parser
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, List, Optional

from .target_models import TargetCandidate, TargetQuery
from .file_intelligence.file_service import FileIntelligenceService
from .semantic_query_parser import SemanticQueryParser, ParsedSemanticQuery

# Forward reference for type checking
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .target_models import ConversationContext


class FileTargetProvider:
    """
    Deterministic file target candidate provider.

    Discovers matching files across standard user locations
    (Downloads, Documents, Desktop, Workspace) and scores candidates.

    Level 3.8.5: Uses SemanticQueryParser to extract recency, extension,
    and location preferences from natural language before discovery.
    """

    VERSION = "3.8.6"

    # Type-word -> extension inference (fixes "newest spreadsheet"
    # recency-only fragility). Keys are bare type words, values carry
    # the leading dot used by Path.suffix.
    _TYPE_WORD_TO_EXT = {
        "spreadsheet": ".xlsx",
        "document": ".docx",
        "presentation": ".pptx",
        "pdf": ".pdf",
        "image": ".png",
        "photo": ".jpg",
        "text": ".txt",
        "csv": ".csv",
    }

    _DEFAULT_ACCEPTANCE = 0.40
    _RECENCY_RELAXED_ACCEPTANCE = 0.30

    # Directories never descended into during recursive fallback search.
    _SKIP_DIR_NAMES = frozenset({
        "__pycache__", ".venv", "venv", "node_modules", ".git",
    })
    _RECURSIVE_MAX_DEPTH = 3
    _RECURSIVE_ENTRY_CAP = 2000

    def __init__(
        self,
        service: Optional[FileIntelligenceService] = None,
        search_roots: Optional[List[Path]] = None,
    ) -> None:
        self.service = service or FileIntelligenceService()
        self._parser = SemanticQueryParser()
        if search_roots is not None:
            self.search_roots = [Path(r) for r in search_roots]
        else:
            home = Path.home()
            self.search_roots = [
                Path.cwd(),
                home / "Downloads",
                home / "Documents",
                home / "Desktop",
            ]

    def discover(
        self,
        query: TargetQuery | str,
        context: Optional["ConversationContext"] = None,
    ) -> tuple[TargetCandidate, ...]:
        """
        Discover candidate files matching the TargetQuery.

        When *context* is provided and the query contains a pronoun
        ("that file", "same folder"), the context resolves the pronoun
        to a previously mentioned filesystem object.
        """
        if isinstance(query, str):
            text = query.strip()
            extension = None
            target_type = "file"
            recency_preference = None
            location_hint = None
        else:
            text = query.text.strip() if query.text else ""
            extension = query.extension
            target_type = query.target_type
            recency_preference = query.recency_preference
            location_hint = query.location_hint

        if not text:
            return ()

        # Parse semantic preferences from natural language
        parsed = self._parser.parse(text)

        # --- Contextual reference resolution ---
        # If the query is a pronoun ("that file", "same folder"),
        # resolve it against conversation history before scoring.
        # Compute name_terms early so context resolution can use them.
        query_terms = [t for t in text.lower().replace("-", " ").replace("_", " ").split() if len(t) > 1]
        name_stop_words = frozenset({
            "my", "the", "a", "an", "in", "on", "at", "to",
            "newest", "latest", "recent",
            "most", "recently", "oldest", "oldest", "biggest",
            "smallest", "largest", "first", "last", "next", "previous",
            "folder", "directory", "file", "files",
            "download", "downloads", "desktop", "pictures",
            "original", "copy", "of", "duplicate", "backup",
            "same", "that", "this", "open", "it",
            "document", "documents",
        })
        name_terms = [t for t in query_terms if t not in name_stop_words and len(t) > 1]

        # Merge parsed preferences with explicit query fields (compute early for context resolution)
        effective_extension = extension or parsed.extension
        effective_recency = recency_preference or parsed.recency
        effective_location = location_hint or parsed.location
        effective_concept = parsed.concept

        # --- Type-word -> extension inference ---
        # When the query has a type word (e.g. "spreadsheet") but no
        # explicit extension, infer effective_extension from the map.
        # Fixes "newest spreadsheet" recency-only fragility.
        if not effective_extension:
            inferred = self._infer_extension_from_type_word(
                text, getattr(parsed, "file_type", None)
            )
            if inferred:
                effective_extension = inferred
        if effective_extension and not effective_extension.startswith("."):
            effective_extension = "." + effective_extension
            effective_extension = effective_extension.lower()
        elif effective_extension:
            effective_extension = effective_extension.lower()

        # --- Disambiguate "documents" as location vs file type ---
        # "in documents" / "my documents" → location (discard extension)
        # "newest documents" / "find documents" → file type (keep extension)
        _LOC_PREPS = frozenset({"in", "at", "on", "from", "inside", "within"})
        _LOC_WORDS = frozenset({
            "downloads", "documents", "desktop", "pictures",
            "music", "videos", "workspace",
        })
        if effective_location and effective_extension:
            query_lower = text.lower()
            words = query_lower.split()
            for i, word in enumerate(words):
                if word in _LOC_WORDS and i > 0:
                    if words[i - 1] in _LOC_PREPS:
                        effective_extension = None
                        break

        # --- Contextual reference resolution ---
        # Honest pronoun handling:
        #  - If context resolves, return the resolved object.
        #  - If parsed.contextual_reference is set but context is None or
        #    resolve_pronoun() returns None, NEVER invent a path. Instead:
        #      1) check session-last-path env vars (GENESIS_SESSION_LAST_PATH /
        #         GENESIS_LAST_PATH) — return only if the path exists on disk;
        #      2) if name_terms is empty, fall back to the newest file across
        #         search roots (confidence 0.45 + pronoun_fallback True);
        #      3) otherwise continue with the normal term-based search.
        if parsed.contextual_reference:
            resolved_path: Optional[str] = None
            if context is not None:
                try:
                    resolved_path = context.resolve_pronoun(text)
                except Exception:
                    resolved_path = None
            if resolved_path:
                import os as _os
                if parsed.contextual_reference == "file" and _os.path.isfile(resolved_path):
                    try:
                        stat = _os.stat(resolved_path)
                        return (TargetCandidate(
                            target_id="context-resolved-0",
                            target_type="file",
                            display_name=_os.path.basename(resolved_path),
                            value=resolved_path,
                            confidence=0.92,
                            source="context_resolution",
                            metadata={
                                "extension": _os.path.splitext(resolved_path)[1].lower(),
                                "parent": _os.path.dirname(resolved_path),
                                "mtime": stat.st_mtime,
                                "size": stat.st_size,
                                "context_resolved": True,
                            },
                        ),)
                    except OSError:
                        pass
                elif parsed.contextual_reference == "folder" and _os.path.isdir(resolved_path):
                    return self._discover_in_folder(
                        resolved_path, name_terms,
                        effective_extension, effective_recency,
                        effective_concept,
                    )
            else:
                # Pronoun unresolved — honest fallbacks only, no invented paths.
                env_last = os.environ.get(
                    "GENESIS_SESSION_LAST_PATH"
                ) or os.environ.get("GENESIS_LAST_PATH")
                if env_last:
                    try:
                        _ep = Path(env_last)
                        if _ep.is_file() and _ep.exists():
                            _estat = _ep.stat()
                            return (TargetCandidate(
                                target_id="context-resolved-env-0",
                                target_type="file",
                                display_name=_ep.name,
                                value=str(_ep.resolve()),
                                confidence=0.60,
                                source="context_resolution",
                                metadata={
                                    "extension": _ep.suffix.lower(),
                                    "parent": str(_ep.parent),
                                    "mtime": _estat.st_mtime,
                                    "size": _estat.st_size,
                                    "pronoun_fallback": True,
                                    "session_last_path": True,
                                },
                            ),)
                    except Exception:
                        pass
                if not name_terms:
                    # No name terms (e.g. bare "that file" / "open it") with
                    # no resolvable context — return () honestly. Guessing
                    # the newest file would be an invented resolution and
                    # breaks the no-context contract.
                    return ()

        candidates: List[TargetCandidate] = []
        seen_paths: set[str] = set()
        candidate_idx = 0

        # Determine effective search roots based on location hint
        search_roots = self._get_effective_roots(effective_location)

        # 1. Direct path check if text looks like an existing path
        try:
            p = Path(text)
            if p.is_file() and p.exists():
                resolved = str(p.resolve())
                seen_paths.add(resolved)
                stat = p.stat()
                candidates.append(
                    TargetCandidate(
                        target_id=f"file-candidate-{candidate_idx}",
                        target_type="file",
                        display_name=p.name,
                        value=resolved,
                        confidence=0.98,
                        source="direct_path",
                        metadata={
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        },
                    )
                )
                candidate_idx += 1
        except Exception:
            pass

        # 2. Search configured roots
        for root in search_roots:
            if not root.exists() or not root.is_dir():
                continue

            try:
                for entry in root.iterdir():
                    if not entry.is_file():
                        continue

                    entry_path = str(entry.resolve())
                    if entry_path in seen_paths:
                        continue

                    try:
                        stat = entry.stat()
                        mtime = stat.st_mtime
                    except (OSError, PermissionError):
                        continue

                    score = self._score_file(
                        entry, name_terms, effective_extension,
                        effective_recency, mtime, effective_concept,
                    )
                    threshold, relaxed = self._acceptance_threshold(
                        entry, effective_extension, effective_recency
                    )
                    if score > threshold:
                        seen_paths.add(entry_path)
                        _meta = {
                            "extension": entry.suffix.lower(),
                            "parent": str(root),
                            "mtime": mtime,
                            "size": stat.st_size,
                        }
                        if relaxed:
                            _meta["recency_relaxed"] = True
                        candidates.append(
                            TargetCandidate(
                                target_id=f"file-candidate-{candidate_idx}",
                                target_type="file",
                                display_name=entry.name,
                                value=entry_path,
                                confidence=score,
                                source="file_provider",
                                metadata=_meta,
                            )
                        )
                        candidate_idx += 1
            except (OSError, PermissionError):
                continue

        # 3. Recursive fallback: only when top-level scan found < 5
        # candidates. Walks up to depth 3, caps at 2000 entries total,
        # skips hidden dirs (leading ".") and __pycache__/.venv/node_modules/.git.
        # Scored identically to top-level hits; tagged recursive=True.
        if len(candidates) < 5:
            scanned = 0
            for root in search_roots:
                if scanned >= self._RECURSIVE_ENTRY_CAP:
                    break
                if not root.exists() or not root.is_dir():
                    continue
                for entry in self._iter_recursive_files(root):
                    scanned += 1
                    if scanned > self._RECURSIVE_ENTRY_CAP:
                        break
                    try:
                        entry_path = str(entry.resolve())
                    except (OSError, PermissionError):
                        continue
                    if entry_path in seen_paths:
                        continue
                    try:
                        stat = entry.stat()
                        mtime = stat.st_mtime
                    except (OSError, PermissionError):
                        continue
                    score = self._score_file(
                        entry, name_terms, effective_extension,
                        effective_recency, mtime, effective_concept,
                    )
                    threshold, relaxed = self._acceptance_threshold(
                        entry, effective_extension, effective_recency
                    )
                    if score > threshold:
                        seen_paths.add(entry_path)
                        _meta = {
                            "extension": entry.suffix.lower(),
                            "parent": str(entry.parent),
                            "mtime": mtime,
                            "size": stat.st_size,
                            "recursive": True,
                        }
                        if relaxed:
                            _meta["recency_relaxed"] = True
                        candidates.append(
                            TargetCandidate(
                                target_id=f"file-candidate-{candidate_idx}",
                                target_type="file",
                                display_name=entry.name,
                                value=entry_path,
                                confidence=score,
                                source="file_provider",
                                metadata=_meta,
                            )
                        )
                        candidate_idx += 1

        # Sort: recency-first when recency preference is set
        if effective_recency and effective_recency in (
            "newest", "latest", "most_recent", "recent",
        ):
            candidates.sort(
                key=lambda c: c.metadata.get("mtime", 0),
                reverse=True,
            )
            # Boost the top candidate significantly for recency queries
            if candidates:
                top = candidates[0]
                boosted = min(0.98, top.confidence + 0.15)
                candidates[0] = TargetCandidate(
                    target_id=top.target_id,
                    target_type=top.target_type,
                    display_name=top.display_name,
                    value=top.value,
                    confidence=boosted,
                    source=top.source,
                    metadata={**top.metadata, "recency_boosted": True},
                )
        elif effective_recency and effective_recency in ("oldest", "first"):
            candidates.sort(
                key=lambda c: c.metadata.get("mtime", 0),
            )
        else:
            candidates.sort(key=lambda c: c.confidence, reverse=True)

        return tuple(candidates)

    def _discover_in_folder(
        self,
        folder_path: str,
        name_terms: list[str],
        required_ext: Optional[str],
        recency: Optional[str],
        concept: Optional[str],
    ) -> tuple[TargetCandidate, ...]:
        """Search a single folder for matching files (used by context resolution)."""
        from pathlib import Path as _P
        import os as _os

        root = _P(folder_path)
        if not root.exists() or not root.is_dir():
            return ()

        candidates: list[TargetCandidate] = []
        seen_paths: set[str] = set()

        for entry in root.iterdir():
            if not entry.is_file():
                continue
            entry_path = str(entry.resolve())
            if entry_path in seen_paths:
                continue
            try:
                stat = entry.stat()
                mtime = stat.st_mtime
            except (OSError, PermissionError):
                continue

            # If no name terms, include all files (context-only resolution)
            if not name_terms:
                score = 0.50
            else:
                score = self._score_file(
                    entry, name_terms, required_ext, recency, mtime, concept,
                )
            threshold, relaxed = self._acceptance_threshold(
                entry, required_ext, recency
            )
            if score > threshold:
                seen_paths.add(entry_path)
                _meta = {
                    "extension": entry.suffix.lower(),
                    "parent": str(root),
                    "mtime": mtime,
                    "size": stat.st_size,
                }
                if relaxed:
                    _meta["recency_relaxed"] = True
                candidates.append(TargetCandidate(
                    target_id=f"file-candidate-{len(candidates)}",
                    target_type="file",
                    display_name=entry.name,
                    value=entry_path,
                    confidence=score,
                    source="file_provider",
                    metadata=_meta,
                ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return tuple(candidates)

    def _iter_recursive_files(self, root: Path) -> Iterable[Path]:
        """Yield files under *root* up to _RECURSIVE_MAX_DEPTH levels deep.

        Top-level (iterdir) hits are already covered by discover(); this
        iterator still includes depth-1 files (cheap dedupe via seen_paths
        in the caller) but its value is depths 2..3. Hidden directories
        (name starting with ".") and _SKIP_DIR_NAMES are never descended
        into. Symlink loops are avoided via a visited-dir set.
        """
        from collections import deque

        max_depth = self._RECURSIVE_MAX_DEPTH
        cap = self._RECURSIVE_ENTRY_CAP
        yielded = 0
        visited: set[str] = set()
        try:
            root_resolved = str(root.resolve())
        except (OSError, PermissionError):
            return
        visited.add(root_resolved)

        queue: deque[tuple[Path, int]] = deque([(root, 0)])
        while queue and yielded < cap:
            current, depth = queue.popleft()
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except (OSError, PermissionError):
                continue
            for dirent in entries:
                if yielded >= cap:
                    break
                try:
                    name = dirent.name
                except (OSError, PermissionError):
                    continue
                try:
                    if dirent.is_dir(follow_symlinks=False):
                        if depth >= max_depth:
                            continue
                        if name.startswith("."):
                            continue
                        if name in self._SKIP_DIR_NAMES:
                            continue
                        try:
                            real = str(Path(dirent.path).resolve())
                        except (OSError, PermissionError):
                            continue
                        if real in visited:
                            continue
                        visited.add(real)
                        queue.append((Path(dirent.path), depth + 1))
                    elif dirent.is_file(follow_symlinks=False):
                        yielded += 1
                        yield Path(dirent.path)
                except (OSError, PermissionError):
                    continue

    def _find_newest_file(
        self, search_roots: List[Path]
    ) -> Optional[TargetCandidate]:
        """Return the newest file across *search_roots* (honest fallback).

        Used only when a pronoun is unresolved AND the query carries no
        name terms (e.g. bare "open it" with empty history). Returns None
        when no file exists — the caller then returns () honestly instead
        of inventing a path.
        """
        newest_path: Optional[Path] = None
        newest_mtime = -1.0
        newest_size = 0
        for root in search_roots:
            if not root.exists() or not root.is_dir():
                continue
            try:
                for entry in root.iterdir():
                    if not entry.is_file():
                        continue
                    try:
                        stat = entry.stat()
                    except (OSError, PermissionError):
                        continue
                    if stat.st_mtime > newest_mtime:
                        newest_mtime = stat.st_mtime
                        newest_path = entry
                        newest_size = stat.st_size
            except (OSError, PermissionError):
                continue
        if newest_path is None:
            return None
        try:
            resolved = str(newest_path.resolve())
        except (OSError, PermissionError):
            return None
        return TargetCandidate(
            target_id="file-candidate-pronoun-fallback-0",
            target_type="file",
            display_name=newest_path.name,
            value=resolved,
            confidence=0.45,
            source="file_provider",
            metadata={
                "extension": newest_path.suffix.lower(),
                "parent": str(newest_path.parent),
                "mtime": newest_mtime,
                "size": newest_size,
                "pronoun_fallback": True,
                "pronoun_unresolved": True,
            },
        )

    def _get_effective_roots(self, location_hint: Optional[str]) -> List[Path]:
        """Get search roots narrowed by location hint.

        When a location hint is provided, check the provider's search_roots
        first by matching the hint against root directory names. If a match
        is found, only that root is searched. Otherwise, fall back to the
        standard location map.
        """
        if not location_hint:
            return self.search_roots

        hint_lower = location_hint.lower().strip()

        # First check if the hint matches any of the provider's search_roots
        for root in self.search_roots:
            if root.name.lower() == hint_lower:
                return [root]
            # Also check common aliases
            if hint_lower == "downloads" and "download" in root.name.lower():
                return [root]
            if hint_lower == "documents" and "document" in root.name.lower():
                return [root]
            if hint_lower == "workspace" and ("workspace" in root.name.lower() or "project" in root.name.lower()):
                return [root]

        # Fall back to standard location map
        location_map = {
            "downloads": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "desktop": Path.home() / "Desktop",
            "pictures": Path.home() / "Pictures",
            "music": Path.home() / "Music",
            "videos": Path.home() / "Videos",
            "workspace": self.search_roots[0] if self.search_roots else Path.cwd(),
        }

        hinted = location_map.get(hint_lower)
        if hinted and hinted.exists():
            return [hinted]

        return self.search_roots

    @classmethod
    def _infer_extension_from_type_word(
        cls, text: str, file_type: Optional[str] = None
    ) -> Optional[str]:
        """Infer an extension from a bare type word in *text*.

        Used when the query carries a type word ("newest spreadsheet")
        but no explicit extension (no ".xlsx" literal and no parser
        extension). Returns the dotted, lowercased extension or None.
        """
        # Prefer the parser's file_type when it maps directly.
        if file_type:
            ft = file_type.lower().strip()
            if ft in cls._TYPE_WORD_TO_EXT:
                return cls._TYPE_WORD_TO_EXT[ft]
        if not text:
            return None
        lower = text.lower()
        for type_word, ext in cls._TYPE_WORD_TO_EXT.items():
            if re.search(rf"\b{re.escape(type_word)}\b", lower):
                return ext
        return None

    @classmethod
    def _acceptance_threshold(
        cls,
        entry: Path,
        effective_extension: Optional[str],
        effective_recency: Optional[str],
    ) -> tuple[float, bool]:
        """Return (threshold, relaxed) for a candidate file.

        Default acceptance is 0.40. When recency is set and the
        candidate's extension matches the effective extension, lower
        acceptance to 0.30 for that candidate only.
        """
        if effective_recency and effective_extension:
            try:
                if entry.suffix.lower() == effective_extension.lower():
                    return cls._RECENCY_RELAXED_ACCEPTANCE, True
            except (OSError, ValueError):
                pass
        return cls._DEFAULT_ACCEPTANCE, False

    # Patterns that indicate a file is a copy / duplicate / backup
    _COPY_PATTERNS = (
        "_copy", " copy", "(copy)",
        "_duplicate", " duplicate",
        "_backup", "_bak", ".bak",
        "copy of ", "Copy of ",
        " - copy", " - Copy",
    )

    @staticmethod
    def _is_copy(entry_name: str) -> bool:
        """Return True if the filename looks like a copy / backup."""
        lower = entry_name.lower()
        return any(pat in lower for pat in FileTargetProvider._COPY_PATTERNS)

    @staticmethod
    def _score_file(
        entry: Path,
        name_terms: List[str],
        required_ext: Optional[str],
        recency: Optional[str],
        mtime: float,
        concept: Optional[str] = None,
    ) -> float:
        name_lower = entry.name.lower()
        stem_lower = entry.stem.lower()
        ext_lower = entry.suffix.lower()

        # Normalize underscores/hyphens to spaces for matching
        # so "project report" matches "project_report.docx"
        name_normalized = name_lower.replace("_", " ").replace("-", " ")
        stem_normalized = stem_lower.replace("_", " ").replace("-", " ")

        score = 0.0

        # Extension filter / match
        has_ext_match = False
        if required_ext:
            if ext_lower != required_ext.lower():
                return 0.0
            score += 0.35  # Strong base for extension match
            has_ext_match = True

        if not name_terms:
            if score > 0 and recency:
                age_seconds = time.time() - mtime
                if recency in ("newest", "latest", "most_recent"):
                    if age_seconds < 86400:
                        score += 0.20
                    elif age_seconds < 7 * 86400:
                        score += 0.15
                    elif age_seconds < 30 * 86400:
                        score += 0.10
                    elif age_seconds < 365 * 86400:
                        score += 0.05
                elif recency in ("oldest", "first"):
                    if age_seconds > 365 * 86400:
                        score += 0.15
                    elif age_seconds > 30 * 86400:
                        score += 0.10
            if concept and score > 0:
                is_copy_file = FileTargetProvider._is_copy(entry.name)
                if concept == "original":
                    score = score * 0.75 if is_copy_file else score + 0.10
                elif concept in ("copy", "duplicate", "backup"):
                    score = score + 0.25 if is_copy_file else score * 0.55
            return min(0.95, score) if score > 0 else 0.0

        # Exact match (normalized)
        query_str = " ".join(name_terms)
        if query_str == name_normalized or query_str == stem_normalized:
            score = 0.96
        # Substring match (normalized)
        elif query_str in name_normalized:
            score += 0.55
        else:
            # Term overlap
            matched_terms = sum(1 for term in name_terms if term in name_normalized)
            if matched_terms > 0:
                score += 0.45 * (matched_terms / len(name_terms))
            elif has_ext_match:
                # Extension matches but no name terms match.
                # This covers type-based queries like "newest spreadsheet"
                # or "oldest photo" where the type word is not in filenames.
                # Give a moderate score so these files are discoverable.
                score += 0.25
            else:
                return 0.0

        # Recency scoring
        if recency:
            age_seconds = time.time() - mtime
            if recency in ("newest", "latest", "most_recent"):
                # Newer files get higher scores
                if age_seconds < 86400:  # < 1 day
                    score += 0.20
                elif age_seconds < 7 * 86400:  # < 1 week
                    score += 0.15
                elif age_seconds < 30 * 86400:  # < 1 month
                    score += 0.10
                elif age_seconds < 365 * 86400:  # < 1 year
                    score += 0.05
            elif recency in ("yesterday",):
                # Files modified in the last 1-2 days
                if 0 < age_seconds < 2 * 86400:
                    score += 0.25
            elif recency in ("today",):
                if age_seconds < 86400:
                    score += 0.25
            elif recency in ("oldest", "first"):
                # Older files get higher scores (inverted)
                if age_seconds > 365 * 86400:
                    score += 0.15
                elif age_seconds > 30 * 86400:
                    score += 0.10
            elif recency in ("recent",):
                if age_seconds < 7 * 86400:
                    score += 0.10
            elif recency in ("last_week", "this_week"):
                if age_seconds < 7 * 86400:
                    score += 0.15
            elif recency in ("last_month", "this_month"):
                if age_seconds < 30 * 86400:
                    score += 0.10
        else:
            # Default recency boost (mild)
            if mtime and time.time() - mtime < 7 * 86400:
                score += 0.05

        # --- Concept scoring: original vs copy vs backup ---
        if concept and score > 0:
            is_copy_file = FileTargetProvider._is_copy(entry.name)
            if concept == "original":
                if is_copy_file:
                    score *= 0.75
                else:
                    score += 0.10
            elif concept in ("copy", "duplicate", "backup"):
                if is_copy_file:
                    score += 0.25
                else:
                    score *= 0.55

        return min(0.95, score)
