"""
Genesis OS — Level 3.8.4
Folder Target Provider.

Adapter connecting FolderManager and system path resolution
to the Level 3.8.4 TargetResolver.

This layer performs read-only folder discovery.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, List, Optional

from .target_models import TargetCandidate, TargetQuery
from .filesystem.folder_manager import FolderManager


class FolderTargetProvider:
    """
    Deterministic folder target candidate provider.

    Resolves standard Windows directories (Downloads, Documents, Desktop,
    Pictures, Music, Videos, Workspace) and custom folder paths.
    """

    VERSION = "3.8.5"

    # Directories never descended into during recursive fallback search.
    _SKIP_DIR_NAMES = frozenset({
        "__pycache__", ".venv", "venv", "node_modules", ".git",
    })
    _RECURSIVE_MAX_DEPTH = 3
    _RECURSIVE_ENTRY_CAP = 2000

    def __init__(
        self,
        manager: Optional[FolderManager] = None,
    ) -> None:
        self.manager = manager or FolderManager()
        home = Path.home()
        self.standard_folders = {
            "downloads": home / "Downloads",
            "download": home / "Downloads",
            "documents": home / "Documents",
            "document": home / "Documents",
            "desktop": home / "Desktop",
            "pictures": home / "Pictures",
            "photos": home / "Pictures",
            "music": home / "Music",
            "videos": home / "Videos",
            "video": home / "Videos",
            "project": Path.cwd(),
            "workspace": Path.cwd(),
            "current": Path.cwd(),
        }

    def discover(self, query: TargetQuery | str) -> tuple[TargetCandidate, ...]:
        """
        Discover candidate folders matching the TargetQuery.
        """
        if isinstance(query, str):
            text = query.strip()
        else:
            text = query.text.strip() if query.text else ""

        if not text:
            return ()

        query_lower = text.lower().strip()
        candidates: List[TargetCandidate] = []
        candidate_idx = 0

        # 1. Direct standard folder name match
        for name, folder_path in self.standard_folders.items():
            if query_lower == name or query_lower == f"my {name}" or query_lower == f"{name} folder" or query_lower == f"my {name} folder":
                if folder_path.exists():
                    candidates.append(
                        TargetCandidate(
                            target_id=f"folder-candidate-{candidate_idx}",
                            target_type="folder",
                            display_name=name.capitalize(),
                            value=str(folder_path.resolve()),
                            confidence=0.98,
                            source="standard_folder",
                            metadata={"standard_name": name},
                        )
                    )
                    candidate_idx += 1

        # 2. Direct path check if text is a valid directory
        try:
            p = Path(text)
            if p.is_dir() and p.exists():
                resolved = str(p.resolve())
                if not any(c.value == resolved for c in candidates):
                    candidates.append(
                        TargetCandidate(
                            target_id=f"folder-candidate-{candidate_idx}",
                            target_type="folder",
                            display_name=p.name or text,
                            value=resolved,
                            confidence=0.98,
                            source="direct_path",
                            metadata={},
                        )
                    )
                    candidate_idx += 1
        except Exception:
            pass

        # 3. Subdirectories in workspace - only match on meaningful name overlap
        try:
            cwd = Path.cwd()
            for sub in cwd.iterdir():
                if sub.is_dir() and not sub.name.startswith((".", "_")):
                    sub_name = sub.name.lower()
                    # Require significant name overlap: exact match, prefix, or fuzzy with high similarity
                    # Avoid spurious matches like "folder" in "definitely_missing_folder"
                    query_words = set(query_lower.split())
                    sub_words = set(sub_name.split())
                    
                    exact_match = query_lower == sub_name
                    prefix_match = sub_name.startswith(query_lower) or query_lower.startswith(sub_name)
                    word_overlap = len(query_words & sub_words) > 0 and min(len(query_words), len(sub_words)) <= 3
                    
                    # Must have meaningful similarity, not just substring containment
                    if exact_match or prefix_match or (word_overlap and not (len(query_lower) < 4 and query_lower in sub_name)):
                        resolved = str(sub.resolve())
                        if not any(c.value == resolved for c in candidates):
                            candidates.append(
                                TargetCandidate(
                                    target_id=f"folder-candidate-{candidate_idx}",
                                    target_type="folder",
                                    display_name=sub.name,
                                    value=resolved,
                                    confidence=0.85,
                                    source="workspace_subfolder",
                                    metadata={"parent": str(cwd)},
                                )
                            )
                            candidate_idx += 1
        except (OSError, PermissionError):
            pass

        # 4. Recursive fallback: only when top-level scan found < 5
        # candidates. Walks workspace up to depth 3, caps at 2000 entries,
        # skips hidden dirs (leading "." / "_") and
        # __pycache__/.venv/node_modules/.git. Scored with the same
        # overlap logic; tagged recursive=True. Never invents paths —
        # only yields directories that exist on disk.
        if len(candidates) < 5:
            try:
                cwd = Path.cwd()
                seen_values = {c.value for c in candidates}
                scanned = 0
                for sub in self._iter_recursive_dirs(cwd):
                    scanned += 1
                    if scanned > self._RECURSIVE_ENTRY_CAP:
                        break
                    sub_name = sub.name.lower()
                    query_words = set(query_lower.split())
                    sub_words = set(sub_name.split())
                    exact_match = query_lower == sub_name
                    prefix_match = sub_name.startswith(query_lower) or query_lower.startswith(sub_name)
                    word_overlap = len(query_words & sub_words) > 0 and min(len(query_words), len(sub_words)) <= 3
                    if exact_match or prefix_match or (word_overlap and not (len(query_lower) < 4 and query_lower in sub_name)):
                        resolved = str(sub.resolve())
                        if resolved not in seen_values:
                            seen_values.add(resolved)
                            candidates.append(
                                TargetCandidate(
                                    target_id=f"folder-candidate-{candidate_idx}",
                                    target_type="folder",
                                    display_name=sub.name,
                                    value=resolved,
                                    confidence=0.70,
                                    source="workspace_subfolder",
                                    metadata={"parent": str(sub.parent), "recursive": True},
                                )
                            )
                            candidate_idx += 1
                            if len(candidates) >= 5:
                                break
            except (OSError, PermissionError):
                pass

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return tuple(candidates)

    def _iter_recursive_dirs(self, root: Path) -> Iterable[Path]:
        """Yield subdirectories under *root* up to _RECURSIVE_MAX_DEPTH deep.

        Skips hidden entries and _SKIP_DIR_NAMES; avoids symlink loops.
        """
        from collections import deque

        max_depth = self._RECURSIVE_MAX_DEPTH
        cap = self._RECURSIVE_ENTRY_CAP
        yielded = 0
        visited: set[str] = set()
        try:
            visited.add(str(root.resolve()))
        except (OSError, PermissionError):
            return
        queue: deque[tuple[Path, int]] = deque([(root, 0)])
        while queue and yielded < cap:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
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
                    if not dirent.is_dir(follow_symlinks=False):
                        continue
                except (OSError, PermissionError):
                    continue
                if name.startswith((".", "_")):
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
                yielded += 1
                sub = Path(dirent.path)
                yield sub
                queue.append((sub, depth + 1))
