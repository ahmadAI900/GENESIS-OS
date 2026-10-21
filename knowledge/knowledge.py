"""Genesis OS — Knowledge service (Phase 9 Documents+Data Intelligence).

Real file-backed search over workspace documents. No mocks.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class Knowledge:
    VERSION = "9.1.0"

    def __init__(self, roots: Optional[List[Path]] = None):
        print("[knowledge] Initialized")
        home = Path.home()
        self.roots = [Path(r) for r in (roots or [Path.cwd(), home / "Documents", home / "Downloads"])]
        self._index: Dict[str, str] = {}

    def index_file(self, path: str | Path) -> bool:
        try:
            p = Path(path)
            if not p.is_file():
                return False
            text = self._read_text(p)
            if text is None:
                return False
            self._index[str(p.resolve())] = text
            return True
        except Exception:
            return False

    def _read_text(self, p: Path) -> Optional[str]:
        suf = p.suffix.lower()
        try:
            if suf in (".txt", ".md", ".json", ".csv", ".log"):
                return p.read_text(encoding="utf-8", errors="ignore")
            if suf == ".docx":
                from docx import Document
                doc = Document(str(p))
                return "\n".join(par.text for par in doc.paragraphs)
            if suf == ".xlsx":
                from openpyxl import load_workbook
                wb = load_workbook(str(p), read_only=True, data_only=True)
                try:
                    parts = []
                    for ws in wb.worksheets:
                        for row in ws.iter_rows(values_only=True):
                            parts.append(" ".join(str(c) for c in row if c is not None))
                    return "\n".join(parts)
                finally:
                    # Item 25A (C34): close on every path (best-effort);
                    # the old close ran only after a successful read.
                    try:
                        wb.close()
                    except Exception:
                        pass
            if suf == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(str(p))
                    return "\n".join(page.extract_text() or "" for page in reader.pages)
                except Exception:
                    return None
            if suf == ".pptx":
                try:
                    from pptx import Presentation
                    prs = Presentation(str(p))
                    out = []
                    for slide in prs.slides:
                        for shape in slide.shapes:
                            if hasattr(shape, "text"):
                                out.append(shape.text)
                    return "\n".join(out)
                except Exception:
                    return None
            return None
        except Exception:
            return None

    def search(self, text: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Real keyword search over indexed + on-disk files.

        Returns list of {path, score, snippet}. Empty query -> [].
        Never returns None (old stub returned None).
        """
        if not isinstance(text, str) or not text.strip():
            return []
        terms = [t.lower() for t in text.strip().split() if len(t) > 1]
        if not terms:
            return []
        # Build candidate file list: indexed + walk roots (top 2 levels + recursive txt/md)
        candidates: Dict[str, str] = dict(self._index)
        for root in self.roots:
            try:
                if not root.exists() or not root.is_dir():
                    continue
                # recursive walk, cap 500 files for safety
                count = 0
                for dirpath, _dirs, files in os.walk(root):
                    # limit depth to 4 to avoid full-disk scan
                    try:
                        depth = len(Path(dirpath).relative_to(root).parts)
                    except Exception:
                        depth = 0
                    if depth > 4:
                        _dirs[:] = []
                        continue
                    for fn in files:
                        if count > 500:
                            break
                        fp = Path(dirpath) / fn
                        if fp.suffix.lower() not in (".txt", ".md", ".json", ".csv", ".log", ".docx", ".xlsx", ".pdf", ".pptx"):
                            continue
                        key = str(fp.resolve())
                        if key not in candidates:
                            content = self._read_text(fp)
                            if content:
                                candidates[key] = content
                                count += 1
                    if count > 500:
                        break
            except Exception:
                continue
        results: List[Dict[str, Any]] = []
        for path, content in candidates.items():
            low = content.lower()
            hits = sum(1 for t in terms if t in low)
            if hits == 0:
                continue
            score = hits / len(terms)
            # snippet around first hit
            idx = low.find(terms[0])
            start = max(0, idx - 80)
            snippet = content[start:start + 240].replace("\n", " ")
            results.append({"path": path, "score": round(score, 3), "snippet": snippet})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]
