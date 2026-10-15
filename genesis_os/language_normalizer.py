"""
Genesis OS — Level 3.11
Multilingual Understanding.

A world-class AI operating system must understand its user in
the user's own language — including imperfect grammar.

This module sits IN FRONT of the deterministic routing pipeline:

    user text (any language)
        ↓
    LanguageNormalizer
        ↓
    English OS command (when needed)
        ↓
    existing WorkflowDecisionEngine

Design constraints:

    - Translation only happens when the input is genuinely
      non-English (script detection + language probability).
    - The ORIGINAL text always stays attached to the result so
      responses can remain personal.
    - If the AI engine is unavailable or fails, the normalizer
      declines silently and the pipeline proceeds unchanged —
      never blocking the OS.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class LanguageNormalizer:

    VERSION = "3.11.0"

    # Requests shorter than this are unreliable to classify;
    # single words like "chrome" route fine as-is.
    MIN_TRANSLATION_LENGTH = 6

    MIN_LANGUAGE_CONFIDENCE = 0.60

    def __init__(self, ai_engine=None):
        self.ai_engine = ai_engine

        try:
            from langdetect import DetectorFactory  # noqa: F401
            self._available = True
        except Exception:
            self._available = False

    # =========================================================
    # PUBLIC API
    # =========================================================

    @property
    def available(self) -> bool:
        return self._available and self.ai_engine is not None

    def needs_translation(self, text: Any) -> bool:
        """
        Decide whether the request should be translated before
        routing. Two independent signals:

            1. Non-Latin script present (fast, decisive)
            2. Latin-script text classified as non-English with
               reasonable confidence
        """

        if not isinstance(text, str):
            return False

        cleaned = " ".join(text.split())

        if len(cleaned) < self.MIN_TRANSLATION_LENGTH:
            return False

        # -----------------------------------------------------
        # SIGNAL 1: NON-LATIN SCRIPT
        # -----------------------------------------------------

        if any(
            "\u0900" <= ch <= "\u02FF"   # Latin-adjacent + Indic
            or "\u0370" <= ch <= "\u1FFF"  # Greek/Cyrillic/etc.
            or "\u2E80" <= ch <= "\uFFFD"  # CJK / Hangul / fullwidth
            for ch in cleaned
        ):
            return True

        # -----------------------------------------------------
        # SIGNAL 2: LATIN-SCRIPT LANGUAGE CLASSIFICATION
        # -----------------------------------------------------

        if not self._available:
            return False

        try:
            from langdetect import detect_langs

            candidates = detect_langs(cleaned)

        except Exception:
            return False

        if not candidates:
            return False

        best = candidates[0]

        return (
            best.lang != "en"
            and best.prob >= self.MIN_LANGUAGE_CONFIDENCE
        )

    def to_english_command(self, text: str) -> Optional[Dict[str, str]]:
        """
        Translate one request into an English OS command.

        Returns {"english": ..., "original": ...} or None when
        translation is unavailable or fails honestly.
        """

        if not self.available or not isinstance(text, str):
            return None

        prompt = f"""Translate the user's computer request into ONE clear English operating-system command.

RULES:
- Keep it a COMMAND, not a question.
- Fix grammar/spelling mistakes in the meaning-preserving direction.
- Reply with ONLY the translated command text, nothing else.

Examples:
"abre chrome por favor" -> "open chrome please"
"क्रोम खोलो और यूट्यूब खोलो" -> "open chrome then open youtube"
"мій комп'ютер дуже повільний чому" -> "why is my computer very slow"

USER REQUEST: "{text}"

English command:"""

        raw = None

        for mode in ("cloud", "local"):
            try:
                raw = self.ai_engine.generate_response(
                    prompt,
                    mode=mode,
                )
            except Exception:
                continue

            if isinstance(raw, str) and raw.strip():
                break

            raw = None

        if not raw:
            return None

        english = self._clean_translation(raw)

        if not english or not english.strip():
            return None

        return {
            "english": english.strip(),
            "original": text.strip(),
        }

    # =========================================================
    # INTERNALS
    # =========================================================

    @staticmethod
    def _clean_translation(raw: str) -> str:
        """
        Strip model chatter: quotes, prefixes, explanations.
        The answer must be the first non-empty line that does
        not look like commentary.
        """

        lines = [
            line.strip().strip('"').strip("'").strip()
            for line in str(raw).splitlines()
            if line.strip()
        ]

        skip_prefixes = (
            "english command",
            "translation",
            "answer",
            "output",
            'user request',
        )

        for line in lines:
            lowered = line.lower()

            if any(lowered.startswith(prefix) for prefix in skip_prefixes):
                continue

            # Drop trailing punctuation used by chat models.
            return line.rstrip(".")

        return ""
