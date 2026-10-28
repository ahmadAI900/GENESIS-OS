"""
Genesis OS — Long-Term Memory (Level 1 maturation).

A persistent memory that genuinely knows the user and participates in
answers.

WHAT ACTUALLY RUNS TODAY
------------------------
Facts enter memory only when the user EXPLICITLY asks, via a memory
command (genesis.py routes these to ``handle_command``):

    "remember I moved to Berlin"
        ↓
    LongTermMemory.handle_command()  ->  _REMEMBER_RE
        ↓
    upsert_fact()
        ↓
    long_term_memory.json
        ↓
    recall_context(query)
        ↓
    injected into Level 1 answers, Level 2 agent tasks,
    and memory commands

Forgetting is equally explicit: "forget my name", "forget everything".

NOT YET WIRED — the passive extraction island
----------------------------------------------
This module also contains a complete but UNREACHABLE extraction path:

    learn_from_turn()          -> extract_deterministic()
                               -> extract_with_ai() -> looks_personal()

None of it is called from anywhere in the product. It would infer and
store facts from ordinary conversation WITHOUT the user asking, which is
a different and far more intrusive behaviour than the explicit
"remember X" path above.

It is retained deliberately (Item 5D / 6A) rather than deleted, so the
capability is available, but it is NOT part of the running system and
this docstring previously claimed otherwise. Wiring it is a PRIVACY
decision, not a bug fix: it must only happen behind an explicit,
opt-in memory mode. ``test_memory_extraction_island_stays_unwired.py``
fails if any module outside this file starts calling it, so that
becoming a conscious act rather than an accident.

Design:

    - FACTS are durable key→value knowledge ("user_name",
      "location", "goal", "favorite_food", ...) with category,
      timestamps and update history.
    - Contradictions UPDATE the fact (the newest user statement
      wins) instead of duplicating.
    - Extraction, when it is enabled, is layered: fast deterministic
      patterns first, then an AI extraction pass for everything else.
      (Currently only the explicit path runs; see above.)
    - Nothing here fabricates: if nothing is known, Genesis
      says so.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional


class LongTermMemory:

    VERSION = "3.0.0"

    STORE_FILE = "long_term_memory.json"

    def __init__(
        self,
        memory_manager=None,
        ai_engine=None,
        storage_path: Optional[str] = None,
    ):
        self.memory_manager = memory_manager
        self.ai_engine = ai_engine

        if storage_path is not None:
            self.store_path = storage_path
        elif memory_manager is not None:
            self.store_path = memory_manager._get_file_path(
                self.STORE_FILE
            )
        else:
            self.store_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                self.STORE_FILE,
            )

    # =========================================================
    # STORAGE
    # =========================================================

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.store_path, "r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                return {"version": self.VERSION, "facts": []}

            data.setdefault("facts", [])
            return data

        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"version": self.VERSION, "facts": []}

    def _save(self, data: Dict[str, Any]) -> None:
        data["updated_at"] = datetime.now().isoformat()

        directory = os.path.dirname(os.path.abspath(self.store_path))
        descriptor, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.store_path)}.",
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.store_path)
        except BaseException:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            raise

    # =========================================================
    # FACT OPERATIONS
    # =========================================================

    def all_facts(self) -> List[Dict[str, Any]]:
        return list(self._load().get("facts", []))

    def upsert_fact(
        self,
        key: str,
        value: str,
        category: str = "general",
        confidence: float = 0.9,
    ) -> Optional[Dict[str, Any]]:
        """
        Insert or update one durable fact.

        Returns {"action": "created"|"updated"|"unchanged"}.
        """

        key = self._normalize_fact_key(key)
        value = str(value).strip().rstrip(".").strip()

        if not key or not value:
            return None

        data = self._load()
        facts = data.get("facts", [])

        now = datetime.now().isoformat(timespec="seconds")

        for fact in facts:
            if self._normalize_fact_key(fact.get("key", "")) == key:
                old_value = str(fact.get("value", ""))

                if old_value.lower() == value.lower():
                    fact["last_seen"] = now
                    self._save(data)
                    return {
                        "action": "unchanged",
                        "fact": fact,
                    }

                history = fact.setdefault("history", [])
                history.append({
                    "value": old_value,
                    "until": now,
                })

                fact["previous_value"] = old_value
                fact["value"] = value
                fact["category"] = (
                    category if category != "general" else fact.get("category", "general")
                )
                fact["confidence"] = confidence
                fact["updated_at"] = now
                fact["last_seen"] = now

                self._save(data)

                return {
                    "action": "updated",
                    "fact": fact,
                }

        fact = {
            "key": key,
            "value": value,
            "category": category,
            "confidence": confidence,
            "created_at": now,
            "updated_at": now,
            "last_seen": now,
            "history": [],
        }

        facts.append(fact)
        self._save(data)

        return {"action": "created", "fact": fact}

    def get_fact(self, key: str) -> Optional[Dict[str, Any]]:
        key = self._normalize_fact_key(key)

        for fact in self.all_facts():
            if self._normalize_fact_key(fact.get("key", "")) == key:
                return fact

        return None

    def forget_fact(self, topic: str) -> int:
        """
        Remove facts whose key OR value matches the topic.
        Returns how many were removed.
        """

        topic_clean = topic.strip().lower().replace("_", " ")
        removed = 0

        data = self._load()
        kept = []

        for fact in data.get("facts", []):
            key_text = str(fact.get("key", "")).lower().replace("_", " ")
            value_text = str(fact.get("value", "")).lower()

            if topic_clean in key_text or topic_clean in value_text:
                removed += 1
                continue

            kept.append(fact)

        data["facts"] = kept

        if removed:
            self._save(data)

        return removed

    def forget_everything(self) -> int:
        data = self._load()
        count = len(data.get("facts", []))

        data["facts"] = []
        self._save(data)

        # Also clear the legacy personalization stores.
        if self.memory_manager is not None:
            try:
                self.memory_manager.save_profile({})
                self.memory_manager.save_goals({})
                self.memory_manager.save_preferences({})
            except Exception:
                pass

        return count

    # =========================================================
    # EXTRACTION — DETERMINISTIC LAYER
    # =========================================================

    _DETERMINISTIC_PATTERNS = [
        (
            re.compile(r"\bmy name(?:'s| is)\s+(?P<value>[A-Za-z\u00C0-\u024F ]{2,40})", re.I),
            "user_name", "profile", 1.0,
        ),
        (
            re.compile(r"\bi am\s+(\d{1,3})\s*years?\s*old\b|\bmy age is\s+(\d{1,3})\b", re.I),
            "age", "profile", 1.0,
        ),
        (
            re.compile(r"\bi live in\s+(?P<value>[A-Za-z\u00C0-\u024F ,]{2,50})", re.I),
            "location", "profile", 0.95,
        ),
        (
            re.compile(r"\bi work as (?:a|an)?\s*(?P<value>[A-Za-z ]{2,50})", re.I),
            "profession", "profile", 0.9,
        ),
        (
            re.compile(r"\bmy goal is (?:to\s+)?(?P<value>[^.!?]{3,120})", re.I),
            "main_goal", "goal", 0.95,
        ),
        (
            re.compile(r"\bi(?:'m| am) studying\s+(?P<value>[^.!?]{2,80})", re.I),
            "studying", "profile", 0.9,
        ),
        (
            re.compile(r"\bmy favou?rite\s+(?P<key>[a-zA-Z ]{2,30}?)\s+is\s+(?P<value>[^.!?]{2,80})", re.I),
            None, "preference", 0.85,   # key derived from group
        ),
        (
            re.compile(r"\bmy project is (?:called\s+)?(?P<value>[^.!?]{2,60})", re.I),
            "project", "project", 0.85,
        ),
    ]

    def extract_deterministic(self, text: str) -> List[Dict[str, Any]]:
        extracted = []

        for pattern, key, category, confidence in self._DETERMINISTIC_PATTERNS:
            match = pattern.search(text)

            if not match:
                continue

            groups = match.groupdict()

            if "key" in groups and groups.get("key"):
                fact_key = f"favorite_{groups['key'].strip().replace(' ', '_')}"
            elif key is not None:
                fact_key = key
            else:
                continue

            value = (
                groups.get("value")
                or match.group(1)
                or match.group(2)
            )

            if not value:
                continue

            result = self.upsert_fact(
                fact_key,
                value.strip(),
                category=category,
                confidence=confidence,
            )

            if result and result["action"] in ("created", "updated"):
                extracted.append(result)

        # Mirror into the existing profile/preferences stores so
        # the older personalization surfaces stay consistent.
        self._mirror_legacy(text)

        return extracted

    def _mirror_legacy(self, text: str) -> None:
        if self.memory_manager is None:
            return

        try:
            self.memory_manager.learn_profile(text)
            self.memory_manager.learn_preference(text)
        except Exception:
            pass

    # =========================================================
    # EXTRACTION — AI LAYER
    # =========================================================

    def looks_personal(self, text: str) -> bool:
        if not isinstance(text, str):
            return False

        lowered = text.lower()

        return bool(
            re.search(
                r"\b(i|me|my|mine|we|our)\b",
                lowered,
            )
            and len(lowered.split()) >= 3
        )

    def extract_with_ai(self, text: str) -> List[Dict[str, Any]]:
        """
        Ask the AI engine to identify durable facts. The output
        is untrusted input: only clean key/value pairs with
        safe characters are accepted.
        """

        if self.ai_engine is None or not self.looks_personal(text):
            return []

        prompt = f"""Extract DURABLE facts about the USER from this message.

RULES:
- Only stable, reusable knowledge (identity, location, job, goals, preferences, projects, family, skills).
- NEVER store temporary states, questions, commands, or feelings about today.
- Reply with ONLY a JSON array like:
[{{"key": "short_fact_name", "value": "the fact", "category": "profile|goal|preference|project|general"}}]
- If there are no durable facts reply exactly: []

MESSAGE: "{text}"

JSON:"""

        raw = None

        for mode in ("cloud", "local"):
            try:
                raw = self.ai_engine.generate_response(prompt, mode=mode)
            except Exception:
                continue

            if isinstance(raw, str) and raw.strip():
                break

            raw = None

        if not raw:
            return []

        parsed = self._extract_json_array(raw)

        stored = []

        if isinstance(parsed, list):
            for item in parsed[:5]:
                if not isinstance(item, dict):
                    continue

                key = str(item.get("key", "")).strip()
                value = str(item.get("value", "")).strip()
                category = str(item.get("category", "general")).strip().lower()

                if (
                    not key
                    or not value
                    or len(key) > 40
                    or len(value) > 200
                    or not re.fullmatch(r"[a-z0-9_]+", key.replace(" ", "_").lower())
                ):
                    continue

                result = self.upsert_fact(
                    key,
                    value,
                    category=(
                        category
                        if category in ("profile", "goal", "preference", "project")
                        else "general"
                    ),
                    confidence=0.8,
                )

                if result and result["action"] in ("created", "updated"):
                    stored.append(result)

        return stored

    @staticmethod
    def _extract_json_array(raw: str):
        import json as _json

        raw = raw.strip()

        match = re.search(r"\[.*\]", raw, re.DOTALL)

        if not match:
            return None

        try:
            return _json.loads(match.group(0))
        except (ValueError, _json.JSONDecodeError):
            return None

    # =========================================================
    # MAIN ENTRY — LEARN FROM A TURN
    # =========================================================

    def learn_from_turn(
        self,
        user_text: str,
        assistant_text: str = "",
    ) -> Dict[str, Any]:
        """
        Extract knowledge from one conversation turn.
        Deterministic extraction always runs; AI extraction
        supplements it when available.

        UNREACHABLE FROM THE PRODUCT (Item 6A, 2026-10-15).
        Nothing outside this module calls this method, or
        extract_deterministic()/extract_with_ai()/looks_personal(),
        which only it calls. Facts reach memory today solely through the
        explicit "remember X" path: handle_command -> upsert_fact.

        Kept, not deleted, so the capability exists. Wiring it is a
        PRIVACY decision: it would store facts the user never asked
        Genesis to remember. If it is ever wired, it must be behind an
        explicit, opt-in memory mode --
        test_memory_extraction_island_stays_unwired.py fails if any
        module outside this file starts calling the island, so that
        change has to be deliberate.
        """

        results = {
            "deterministic": [],
            "ai": [],
        }

        if not isinstance(user_text, str) or not user_text.strip():
            return results

        try:
            results["deterministic"] = self.extract_deterministic(user_text)
        except Exception:
            results["deterministic"] = []

        try:
            ai_results = self.extract_with_ai(user_text)

            # Avoid duplicates the deterministic layer already got.
            existing_keys = {
                r["fact"]["key"]
                for r in results["deterministic"]
                if r and r.get("fact")
            }

            results["ai"] = [
                item
                for item in ai_results
                if item["fact"]["key"] not in existing_keys
            ]

        except Exception:
            results["ai"] = []

        return results

    # =========================================================
    # RECALL — CONTEXT FOR ANSWERS
    # =========================================================

    def recall_context(
        self,
        query: str = "",
        max_items: int = 8,
    ) -> str:
        """
        Build a compact memory block for prompts.

        Relevance: keyword overlap between query and
        key/value; when no overlap exists, the most recently
        updated facts are used (identity is always useful).
        """

        facts = self.all_facts()

        if not facts:
            return ""

        scored = []

        query_words = set(
            re.findall(r"[a-z0-9]+", str(query).lower())
        )

        now = datetime.now()

        for fact in facts:
            key_words = set(re.findall(r"[a-z0-9]+", str(fact.get("key", "")).replace("_", " ")))
            value_words = set(re.findall(r"[a-z0-9]+", str(fact.get("value", "")).lower()))

            overlap = len(query_words & (key_words | value_words))

            recency = 0.0
            updated = fact.get("updated_at", "")

            try:
                age_days = (
                    now - datetime.fromisoformat(updated)
                ).days
                recency = max(0.0, 3.0 - age_days / 30.0)
            except Exception:
                recency = 1.0

            identity_boost = 2.0 if fact.get("category") == "profile" else 0.0

            score = overlap * 2.0 + recency + identity_boost

            scored.append((score, fact))

        scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("key"))))

        lines = [
            f"- {self._human_key(f['key'])}: {f['value']}"
            for _, f in scored[:max_items]
        ]

        return "\n".join(lines)

    @staticmethod
    def _human_key(key: str) -> str:
        return str(key).replace("_", " ").strip().capitalize()

    def enrich_prompt(self, query: str) -> str:
        """
        Wrap a user query with remembered context for LLM
        consumption. Returns the original query unchanged when
        nothing relevant is known.
        """

        context = self.recall_context(query)

        if not context:
            return query

        return (
            "[USER MEMORY — use naturally, mention only when "
            "relevant]\n"
            f"{context}\n"
            "[END USER MEMORY]\n\n"
            f"{query}"
        )

    # =========================================================
    # NATURAL MEMORY COMMANDS
    # =========================================================

    _SUMMARY_RE = re.compile(
        r"^what\s+(?:do|did)\s+you\s+(?:know|remember)\s+about\s+me\s*[?.]?$"
        r"|^(?:what\s+do\s+you\s+know|tell\s+me\s+what\s+you\s+remember)\s*$"
        r"|^my\s+memory$|^our\s+memories\s*[?.]?$",
        re.IGNORECASE,
    )

    _FORGET_ALL_RE = re.compile(
        r"^forget\s+(?:everything|all|it\s+all|about\s+me)(?:\s+please)?\s*[.!]?$",
        re.IGNORECASE,
    )

    _FORGET_TOPIC_RE = re.compile(
        r"^forget\s+(?:about\s+)?(?:my\s+)?(.+?)\s*[.!]?$",
        re.IGNORECASE,
    )

    _REMEMBER_RE = re.compile(
        r"^remember\s+(?:that\s+)?(.+)$",
        re.IGNORECASE,
    )

    _DO_YOU_KNOW_RE = re.compile(
        r"^(?:do|did)\s+you\s+know\s+(?:what\s+)?my\s+(?P<topic>[a-zA-Z _]+)\s*[?.]?$",
        re.IGNORECASE,
    )

    def handle_command(self, text: str) -> Optional[str]:
        """
        Answer natural memory-management requests directly.
        Returns a response string or None when the text is not
        a memory command.
        """

        if not isinstance(text, str):
            return None

        cleaned = " ".join(text.split()).strip()

        if not cleaned:
            return None

        if self._SUMMARY_RE.match(cleaned):
            facts = self.all_facts()

            if not facts:
                return (
                    "I don't know anything about you yet. Tell me "
                    "about yourself and I will remember."
                )

            lines = [
                "Here's what I remember about you:",
                *[
                    f"- {self._human_key(f['key'])}: {f['value']}"
                    for f in facts
                ],
            ]

            return "\n".join(lines)

        if self._FORGET_ALL_RE.match(cleaned):
            count = self.forget_everything()
            return (
                "Done — I've forgotten everything."
                if count
                else "There was nothing to forget."
            )

        do_know = self._DO_YOU_KNOW_RE.match(cleaned)
        if do_know:
            fact = self.get_fact(do_know.group("topic"))

            if fact:
                return (
                    f"Yes — your {self._human_key(fact['key']).lower()} "
                    f"is {fact['value']}."
                )

            return (
                f"I don't have your "
                f"{do_know.group('topic').strip()} yet."
            )

        forget_match = self._FORGET_TOPIC_RE.match(cleaned)
        if forget_match:
            topic = forget_match.group(1)

            if topic.strip().lower() in ("everything", "all", "it all", "me"):
                return self.handle_command("forget everything")

            removed = self.forget_fact(topic)

            if removed:
                return f"Forgotten: {topic}."
            return (
                f"I didn't have any memories about '{topic}'."
            )

        remember_match = self._REMEMBER_RE.match(cleaned)
        if remember_match:
            fact_text = remember_match.group(1).strip()

            stored = self.upsert_fact(
                key=self._derive_key(fact_text),
                value=fact_text,
                category="general",
                confidence=1.0,
            )

            return "Remembered."

        return None

    @staticmethod
    def _normalize_fact_key(key: str) -> str:
        """ONE canonical fact-key form: stripped, lowercased, spaces
        and LEGACY hyphens folded to underscores.

        Item 26F (L13): _derive_key used to join with "-" while
        upsert_fact/get_fact normalized with "_" -- a fact stored via
        the derive path ("moved-berlin") was unreachable by
        get_fact("moved berlin") ("moved_berlin"). One normalization
        now covers the store path, the read path and the derive path,
        and folding hyphens on the READ side keeps OLD hyphen-keyed
        stores readable and updatable in place (no duplicates).
        """
        return (
            str(key).strip().lower().replace("-", "_").replace(" ", "_")
        )

    @staticmethod
    def _derive_key(fact_text: str) -> str:
        words = re.findall(r"[a-z0-9]+", fact_text.lower())

        stop = {
            "i", "am", "is", "are", "the", "a", "an", "my",
            "that", "of", "to", "and", "in", "on", "at",
        }

        meaningful = [w for w in words if w not in stop][:4]

        # Item 26F (L13): canonical underscores, so a derived key is
        # directly findable by get_fact (via _normalize_fact_key).
        return "_".join(meaningful) or "note"

    # =========================================================
    # SUMMARY
    # =========================================================

    def summary(self) -> str:
        facts = self.all_facts()

        if not facts:
            return "(no long-term memories yet)"

        return "; ".join(
            f"{f['key']}={f['value']}" for f in facts
        )
