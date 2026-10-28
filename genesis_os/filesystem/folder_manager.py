"""Genesis OS — Safe folder operations."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..file_intelligence.path_security import PathSecurity


class FolderManager:
    VERSION = "3.8.0"

    @staticmethod
    def _validate(path: Any, **kwargs):
        return PathSecurity.validate(path, **kwargs)

    def open(self, path: Any) -> dict:
        v = self._validate(path, require_existing=True, require_directory=True)
        if not v["allowed"]:
            return {"success": False, "operation": "folder.open", "error": v["reason"], "executed": False, "verified": False}
        p = Path(v["path"])
        try:
            import os
            if hasattr(os, "startfile"):
                os.startfile(str(p))
            else:
                import subprocess
                subprocess.Popen(["explorer", str(p)])
            return {
                "success": True,
                "operation": "folder.open",
                "path": str(p),
                "folder": p.name,
                "executed": True,
                "verified": False,
                "verification_type": "dispatch_only",
                "verification_reason": "Explorer dispatch was not independently observed.",
                "message": f"Opened folder '{p.name}'.",
            }
        except OSError as exc:
            return {"success": False, "operation": "folder.open", "path": str(p), "error": str(exc), "executed": False, "verified": False}

    def inspect(self, path: Any) -> dict:
        v = self._validate(path, require_existing=True, require_directory=True)
        if not v["allowed"]:
            return {"success": False, "operation": "folder.inspect", "error": v["reason"]}
        p = Path(v["path"])
        try:
            items = sorted(({"name": x.name, "path": str(x), "is_file": x.is_file(), "is_directory": x.is_dir()}
                            for x in p.iterdir()), key=lambda x: x["path"].casefold())
            return {"success": True, "operation": "folder.inspect", "path": str(p), "items": items,
                    "count": len(items), "executed": False, "verified": True,
                    "folder_exists": True, "post_state_matches": True}
        except OSError as exc:
            return {"success": False, "operation": "folder.inspect", "path": str(p), "error": str(exc)}

    def create(self, path: Any) -> dict:
        v = self._validate(path)
        if not v["allowed"]:
            return {"success": False, "operation": "folder.create", "error": v["reason"]}
        p = Path(v["path"])
        if p.exists():
            return {"success": False, "operation": "folder.create", "status": "already_exists", "path": str(p)}
        try:
            p.mkdir(parents=True)
            verified = p.is_dir()
            return {"success": verified, "operation": "folder.create", "path": str(p), "executed": True,
                    "verified": verified, "folder_exists": verified, "post_state_matches": verified}
        except OSError as exc:
            return {"success": False, "operation": "folder.create", "path": str(p), "error": str(exc)}

    def rename(self, source: Any, new_name: str) -> dict:
        # `confirmed` is ACCEPTED BUT IGNORED (Item 3B-3b). It is no longer
        # an authority: authorization comes only from the executor's
        # blast-radius gate plus a valid AuthorizationGrant. A rename onto
        # an EXISTING target is Tier 1 there and needs a grant; a rename
        # onto a free target is Tier 2 and simply proceeds. Callers may
        # keep passing the flag; it changes nothing.
        v = self._validate(source, require_existing=True, require_directory=True)
        if not v["allowed"]:
            return {"success": False, "operation": "folder.rename", "error": v["reason"]}
        if not isinstance(new_name, str) or not new_name.strip() or Path(new_name).name != new_name:
            return {"success": False, "operation": "folder.rename", "error": "A safe folder name is required."}
        target = Path(v["path"]).parent / new_name.strip()
        try:
            Path(v["path"]).rename(target)
            verified = target.is_dir() and not Path(v["path"]).exists()
            return {"success": verified, "operation": "folder.rename", "path": str(target), "executed": True,
                    "verified": verified, "folder_exists": verified, "post_state_matches": verified}
        except OSError as exc:
            return {"success": False, "operation": "folder.rename", "error": str(exc)}

    def move(self, source: Any, destination: Any) -> dict:
        # `confirmed` accepted but ignored; see rename() and Item 3B-3b.
        v = self._validate(source, require_existing=True, require_directory=True)
        d = self._validate(destination)
        if not v["allowed"]: return {"success": False, "operation": "folder.move", "error": v["reason"]}
        if not d["allowed"]: return {"success": False, "operation": "folder.move", "error": d["reason"]}
        try:
            target = Path(d["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            Path(v["path"]).rename(target)
            verified = target.is_dir() and not Path(v["path"]).exists()
            return {"success": verified, "operation": "folder.move", "path": str(target), "executed": True,
                    "verified": verified, "folder_exists": verified, "post_state_matches": verified}
        except OSError as exc:
            return {"success": False, "operation": "folder.move", "error": str(exc)}

    def delete(self, path: Any) -> dict:
        # `confirmed` accepted but ignored; see rename() and Item 3B-3b.
        # folder.delete is Tier 1 at the executor gate, so reaching this
        # method at all already required a valid AuthorizationGrant.
        v = self._validate(path, require_existing=True, require_directory=True)
        if not v["allowed"]: return {"success": False, "operation": "folder.delete", "error": v["reason"]}
        p = Path(v["path"])
        if any(p.iterdir()):
            return {"success": False, "operation": "folder.delete", "status": "not_empty",
                    "error": "Genesis will not delete a non-empty folder without an explicit recursive policy."}
        try:
            p.rmdir()
            verified = not p.exists()
            return {"success": verified, "operation": "folder.delete", "path": str(p), "executed": True,
                    "verified": verified, "folder_exists": verified, "post_state_matches": verified}
        except OSError as exc:
            return {"success": False, "operation": "folder.delete", "error": str(exc)}

    def organize(self, path: Any, *, dry_run: bool = False) -> dict:
        # `confirmed` accepted but ignored; see rename() and Item 3B-3b.
        v = self._validate(path, require_existing=True, require_directory=True)
        if not v["allowed"]:
            return {"success": False, "operation": "folder.organize", "error": v["reason"], "executed": False, "verified": False}
        p = Path(v["path"])

        category_rules = {
            "Documents": {".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".epub", ".md", ".rtf"},
            "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff"},
            "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
            "Audio & Video": {".mp3", ".mp4", ".mkv", ".wav", ".mov", ".avi", ".flac", ".m4a"},
            "Code & Data": {".py", ".json", ".yaml", ".yml", ".xml", ".html", ".css", ".js", ".ts", ".sql", ".sh"},
            "Installers": {".exe", ".msi", ".iso", ".dmg"},
        }
        category_names = set(category_rules.keys())

        planned_moves = []
        try:
            for item in p.iterdir():
                if not item.is_file() or item.name.startswith((".", "desktop.ini", "Thumbs.db")):
                    continue
                ext = item.suffix.lower()
                target_category = "Other"
                for cat, extensions in category_rules.items():
                    if ext in extensions:
                        target_category = cat
                        break
                if target_category != "Other":
                    planned_moves.append({
                        "file": item.name,
                        "source": str(item),
                        "category": target_category,
                        "destination_folder": str(p / target_category),
                        "destination_path": str(p / target_category / item.name),
                    })
        except OSError as exc:
            return {"success": False, "operation": "folder.organize", "path": str(p), "error": str(exc)}

        if dry_run:
            return {
                "success": True,
                "operation": "folder.organize",
                "path": str(p),
                "organized_count": 0,
                "planned_count": len(planned_moves),
                "planned_moves": planned_moves,
                "message": f"Dry run identified {len(planned_moves)} file move(s); no files were changed.",
                "executed": False,
                "verified": True,
                "post_state_matches": True,
            }

        if not planned_moves:
            return {
                "success": True,
                "operation": "folder.organize",
                "path": str(p),
                "organized_count": 0,
                "moves": [],
                "message": f"Folder '{p.name}' is already organized; no unorganized files found.",
                "executed": False,
                "verified": True,
                "post_state_matches": True,
            }

        # `confirmed` accepted but ignored; see rename() and Item 3B-3b.
        # folder.organize is Tier 1 at the executor gate, so reaching this
        # method already required a valid AuthorizationGrant.

        # Execute organization
        executed_moves = []
        try:
            for move in planned_moves:
                cat_dir = Path(move["destination_folder"])
                cat_dir.mkdir(parents=True, exist_ok=True)
                src = Path(move["source"])
                dst = Path(move["destination_path"])
                if dst.exists():
                    stem = src.stem
                    ext = src.suffix
                    counter = 1
                    while (cat_dir / f"{stem}_{counter}{ext}").exists():
                        counter += 1
                    dst = cat_dir / f"{stem}_{counter}{ext}"
                src.rename(dst)
                executed_moves.append({
                    "file": src.name,
                    "category": move["category"],
                    "destination": str(dst),
                })

            verified = bool(executed_moves) and all(
                Path(move["destination"]).is_file()
                and not Path(move["source"]).exists()
                for move in executed_moves
            )
            success = verified and len(executed_moves) == len(planned_moves)
            return {
                "success": success,
                "operation": "folder.organize",
                "path": str(p),
                "organized_count": len(executed_moves),
                "moves": executed_moves,
                "message": (
                    f"Organized {len(executed_moves)} file(s) into categorized folders in '{p.name}'."
                    if success
                    else "Folder organization could not be fully verified."
                ),
                "executed": True,
                "verified": verified,
                "post_state_matches": verified,
            }
        except OSError as exc:
            return {
                "success": False,
                "operation": "folder.organize",
                "path": str(p),
                "error": str(exc),
                "partial_moves": executed_moves,
                "executed": len(executed_moves) > 0,
                "verified": False,
            }
