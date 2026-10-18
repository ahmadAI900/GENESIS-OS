"""
Genesis OS — Level 3.10
AI Intent Resolution.

The WorkflowDecisionEngine handles known natural patterns with
deterministic precision. But a true AI operating system must
also understand phrasings that no pattern anticipated:

    "make my screen dimmer"
    "kill the sound"
    "capture what's on my monitor"

This module uses the EXISTING Genesis AI engine (Level 1
infrastructure) to map such requests onto the REGISTERED
capability catalog. The AI proposes intent; deterministic code
validates it.

Safety properties:

    - Only registered, enabled, safety-allowed capabilities can
      ever be proposed. Explicit denials (shutdown, shell,
      process kill...) are filtered before anything else.
    - The AI's output is treated as untrusted input: malformed
      JSON, unknown operations, or missing targets are discarded.
    - Resolved intents are capped below the automatic-execution
      confidence threshold and REQUIRE explicit user
      confirmation before execution.

If the AI engine is unavailable or fails, this layer silently
disables itself — the OS remains fully functional through the
deterministic paths.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional


class LLMCircuitBreaker:
    """
    Circuit breaker for LLM fallback calls.

    Tracks consecutive failures.  When the failure count reaches
    the threshold the circuit "trips" and blocks further requests
    for a cooldown period.  After the cooldown the circuit enters
    a half-open state and allows a single probe request; success
    closes the circuit, failure re-trips it.

    Thread-safe: uses a lock so concurrent CLI requests cannot
    race on the counter.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ):
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._tripped_at: float = 0.0
        self._lock = threading.Lock()
        self._disabled = False

    @property
    def is_open(self) -> bool:
        """True when the circuit is blocking requests."""
        with self._lock:
            if not self._disabled:
                return False
            elapsed = time.monotonic() - self._tripped_at
            if elapsed >= self._cooldown_seconds:
                return False
            return True

    @property
    def is_disabled(self) -> bool:
        """True when the circuit has tripped and is currently blocking."""
        with self._lock:
            return self._disabled

    def allow_request(self) -> bool:
        """Return True if a request is allowed through."""
        with self._lock:
            if not self._disabled:
                return True
            elapsed = time.monotonic() - self._tripped_at
            if elapsed >= self._cooldown_seconds:
                return True
            return False

    def record_success(self) -> None:
        """Record a successful call — resets the failure counter."""
        with self._lock:
            self._consecutive_failures = 0
            if self._disabled:
                self._disabled = False

    def record_failure(self) -> None:
        """Record a failed call — may trip the circuit."""
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._disabled = True
                self._tripped_at = time.monotonic()

    def reset(self) -> None:
        """Manual reset — for testing or forced recovery."""
        with self._lock:
            self._consecutive_failures = 0
            self._disabled = False
            self._tripped_at = 0.0


def _record_probe_error(probe: Optional[Dict[str, int]]) -> None:
    """Item 11A: one backend call failed (raised, or returned junk)."""
    if probe is None:
        return
    probe["errors"] = probe.get("errors", 0) + 1


def _record_probe_reply(probe: Optional[Dict[str, int]]) -> None:
    """Item 11A: the provider actually responded."""
    if probe is None:
        return
    probe["replies"] = probe.get("replies", 0) + 1


class LLMIntentResolver:

    VERSION = "3.10.0"

    PROPOSAL_CONFIDENCE_CAP = 0.85

    # Cheap pre-filter so ordinary conversation never reaches
    # the AI layer: the request must look like an imperative
    # command, not just any sentence that happens to contain
    # an action-shaped word. Verbs like "make", "set", "open",
    # "take" appear constantly in casual English ("I make you
    # able to", "you set me up", "take care"), so a substring
    # match on the raw text causes conversational statements
    # to be reinterpreted as commands. The verb must be in
    # imperative position — at the start of the sentence (after
    # an optional polite prefix) or after an explicit intent
    # stem like "i want to" / "i need to" / "let's".
    # Also includes common non-imperative forms (participles,
    # adjectives, phrasal-verb components) so that question-
    # format action requests ("what's eating up my disk space",
    # "how bright is my screen") pass the gate too.
    _ACTION_HINT_RE = re.compile(
        r"\b(open|close|launch|start|stop|create|make|delete|remove|move|"
        r"copy|rename|find|search|play|pause|mute|unmute|set|turn|adjust|"
        r"dim|brighten|bright|lock|organize|sort|capture|take|show|list|"
        r"check|connect|browse|read|write|save|kill|maximize|minimize|snap|"
        r"empty|eject|toggle|switch|change|increase|decrease|lower|raise|"
        r"grab|record|screenshot|clean|shutdown|"
        r"get|stash|eating|playing|stack|running|using|"
        r"boot|shut|press|enter|scroll|highlight|clone|give|wipe|fix|"
        r"condense|navigate|locate|pull|end|go|scan|put|retrieve|jot|"
        r"tell|send|drop|load|fetch|prepare|organise|arrange|compute|"
        r"display|reveal|summarise|summarize|compare|inspect|verify|"
        r"filter|aggregate|group|rank|calculate|"
        r"add|join|relocate|reclaim|derive|total|tally|embed|embed)\b",
        re.IGNORECASE,
    )

    # Polite / intent-introducing prefixes that legitimately
    # precede an imperative verb. The first content word after
    # one of these must itself be an action verb for the
    # sentence to look like a command.
    # Optional leading interjections ("hey", "hi", "yo", "ok",
    # "okay", "alright") that a user may say before the real
    # command. One such word, followed by a comma or end of
    # string, is allowed before the imperative verb.
    _INTERJECTION_RE = re.compile(
        r"^\s*(?:hey|hi|yo|ok(?:ay)?|alright|so|well)[,]?\s+"
        r"(.+)$",
        re.IGNORECASE,
    )

    _POLITE_PREFIX_RE = re.compile(
        r"^\s*(?:please\s+|"
        r"can\s+you\s+|could\s+you\s+|would\s+you\s+|"
        r"i\s+want\s+to\s+|i\s+need\s+to\s+|"
        r"i\s+would\s+like\s+to\s+|"
        r"let(?:'s|s)(?:\s+me|\s+us)?\s+|"
        r"let\s+(?:me|us)\s+)"
        r"(.+)$",
        re.IGNORECASE,
    )

    # Timeout for individual LLM calls (seconds).
    # MEASURED with the enriched catalog: the original flat catalog
    # (16.1k-char prompt) was answered by the local model in
    # 2.73-5.98s. Enrichment grew the prompt, so the budget is set
    # with headroom over the observed local latency while still
    # bounding a stalled provider. Resolution is additionally capped
    # end-to-end by _RESOLVE_TOTAL_BUDGET, because three backends
    # plus a repair round at 15s each permitted a single request to
    # exceed 90s.
    _LLM_CALL_TIMEOUT = 12.0

    # Total wall-clock budget for one resolve() across every
    # backend attempt and the optional repair round.
    _RESOLVE_TOTAL_BUDGET = 22.0

    # Measurement override. MEASURED 2026-09-26: a full enriched
    # catalog is ~5.4k tokens, and against the 120B cloud model
    # that takes 28-40s per call once the account's rolling
    # tokens-per-minute quota is under pressure — far beyond the
    # 22s interactive budget. That is correct for an interactive
    # CLI, which must not stall, but it makes a batch accuracy
    # measurement impossible at production settings. A benchmark
    # can therefore raise the budgets explicitly through the
    # environment. Production defaults are unchanged unless
    # GENESIS_LLM_CALL_TIMEOUT is set.
    _BUDGET_ENV_OVERRIDES = (
        ("_LLM_CALL_TIMEOUT", "GENESIS_LLM_CALL_TIMEOUT", float),
        ("_RESOLVE_TOTAL_BUDGET", "GENESIS_LLM_TOTAL_BUDGET", float),
    )

    @classmethod
    def _apply_budget_overrides(cls) -> None:
        for attr, env_name, caster in cls._BUDGET_ENV_OVERRIDES:
            raw = os.environ.get(env_name)
            if not raw:
                continue
            try:
                value = caster(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                setattr(cls, attr, value)

    # Bounded in-flight provider calls.
    #
    # Python threads cannot be cancelled, so a timed-out call
    # leaves a worker still hammering the provider. Both naive
    # options were measured and both are wrong:
    #
    #   wait=True  -> the timeout is not honoured at all, because
    #                 __exit__ joins the worker. Observed: 51.9s
    #                 for a request with an 8s per-call budget
    #                 and a 22s total budget.
    #   wait=False -> the timeout IS honoured, but abandoned
    #                 workers pile up, saturate the local model
    #                 and turn every later call into another
    #                 timeout. Observed: 7/10 correct collapsed to
    #                 2/10.
    #
    # The fix is a non-blocking call PLUS a cap on concurrently
    # live workers, so abandoned work is bounded instead of
    # unbounded. Once the cap is reached we stop issuing calls
    # rather than making saturation worse.
    _MAX_INFLIGHT_CALLS = 6

    # Overridable for hosts where the default is wrong.
    #
    # MEASURED 2026-09-27 on a CPU-only 11.9 GB host: a 40-item
    # batch of 4.4 GB qwen2.5:7b calls with cap=6 exhausted RAM.
    # One item took 32,017 seconds and the run thrashed, so the
    # benchmark was measuring memory pressure rather than routing.
    # GENESIS_LLM_INFLIGHT_CAP=1 keeps exactly one model call live.
    _INFLIGHT_CAP_ENV = "GENESIS_LLM_INFLIGHT_CAP"

    @classmethod
    def _inflight_cap(cls) -> int:
        raw = os.environ.get(cls._INFLIGHT_CAP_ENV)
        if raw:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return cls._MAX_INFLIGHT_CALLS
            if value >= 1:
                return value
        return cls._MAX_INFLIGHT_CALLS

    # Backend order is overridable so a measurement can pin a single
    # backend instead of retrying across three, which on a slow local
    # model multiplies wall-clock time threefold and exhausts the
    # total budget before the first answer arrives.
    _MODES_ENV = "GENESIS_LLM_MODES"

    @classmethod
    def _backend_modes(cls) -> tuple:
        raw = os.environ.get(cls._MODES_ENV)
        if raw:
            modes = []
            for part in raw.split(","):
                part = part.strip()
                if part == "auto":
                    modes.append(None)
                elif part in ("local", "cloud"):
                    modes.append(part)
            if modes:
                return tuple(modes)
        return ("local", "cloud", None)
    _inflight_calls = 0
    _inflight_lock = threading.Lock()

    @classmethod
    def _acquire_inflight_slot(cls) -> bool:
        cap = cls._inflight_cap()
        with cls._inflight_lock:
            if cls._inflight_calls >= cap:
                return False
            cls._inflight_calls += 1
            return True

    # Longest an abandoned worker may hold a slot.
    #
    # MEASURED 2026-09-28: a timed-out call leaves a worker that
    # still holds its in-flight slot until the provider call
    # actually returns. With GENESIS_LLM_INFLIGHT_CAP=1 — the
    # setting used for batch measurement to stop 4.4 GB model calls
    # piling up — the NEXT request was refused instantly (0.00s,
    # result None) and that item was lost. Reproduced deterministically
    # with a stub engine: slot 1/1 held, next item starved.
    #
    # Holding the slot is right (it bounds concurrent load) but it
    # must not be unbounded, or one slow provider call silently
    # deletes every subsequent request. After this many seconds the
    # slot is force-released; the provider may still be working, so
    # the cap trades a small risk of overshoot for the elimination of
    # starvation.
    _INFLIGHT_HOLD_SECONDS = 240.0

    @classmethod
    def _release_inflight_slot(cls) -> None:
        with cls._inflight_lock:
            if cls._inflight_calls > 0:
                cls._inflight_calls -= 1

    @classmethod
    def _arm_inflight_watchdog(cls) -> None:
        """
        Force-release the current in-flight slot after the hold cap.

        Daemon thread, so it never keeps the process alive.
        """

        def _watch():
            time.sleep(cls._INFLIGHT_HOLD_SECONDS)
            with cls._inflight_lock:
                if cls._inflight_calls > 0:
                    cls._inflight_calls -= 1

        try:
            threading.Thread(
                target=_watch,
                name="genesis-inflight-watchdog",
                daemon=True,
            ).start()
        except Exception:
            # If a watchdog cannot start, fall back to releasing
            # immediately rather than risk permanent starvation.
            cls._release_inflight_slot()

    def __init__(
        self,
        ai_engine=None,
        decision_engine=None,
        circuit_breaker=None,
    ):
        self.ai_engine = ai_engine
        self.decision_engine = decision_engine
        self._circuit_breaker = circuit_breaker or LLMCircuitBreaker()
        self._apply_budget_overrides()

    @staticmethod
    def _command_core(text: str) -> Optional[str]:
        """
        Return the imperative core of a sentence (the part
        that should begin with an action verb).

        Recognized leading material that may be stripped
        before reaching the verb:

            - Polite prefixes ("please", "can you", "could
              you", "i want to", "let's", "let me", ...).
            - Short interjections ("hey", "hi", "yo", "ok",
              "alright", "so", "well") optionally followed
              by a comma.

        These two layers may appear together — a user naturally
        says "hey, can you open notepad" (interjection
        followed by polite) or "ok, please mute the volume"
        (interjection followed by polite). A single pass
        only strips one layer, leaving "can you open
        notepad" whose first word "can" is not an action
        verb. The sentence would be wrongly rejected as
        non-actionable. Two passes strip both layers in
        sequence, leaving "open notepad" which starts with
        a real imperative verb.

        If neither layer matches, the full sentence is
        returned and the caller requires the FIRST word
        itself to be an action verb. This naturally
        rejects conversational sentences that just happen
        to mention a verb in mid-clause position — e.g.
        "hii now i make you able to control my computer".
        """

        stripped = text.strip()

        if not stripped:
            return None

        previous = None
        current = stripped

        # Strip up to two leading layers (interjection +
        # polite). The stripper is idempotent in the no-match
        # case (it returns its input unchanged), so a fixed
        # loop is safe — it terminates after at most two
        # successful strips even on pathological input.
        while previous != current:

            previous = current

            polite = (
                LLMIntentResolver._POLITE_PREFIX_RE.match(
                    current
                )
            )

            if polite is not None:
                current = polite.group(1).strip()
                continue

            interjection = (
                LLMIntentResolver._INTERJECTION_RE.match(
                    current
                )
            )

            if interjection is not None:
                current = (
                    interjection.group(1).strip()
                )
                continue

            break

        return current

    # State verbs / adjectives that express an information-seeking
    # intent in question format.  When a question-format sentence
    # starts with a wh-word and contains one of these, it is an
    # actionable request even though no ACTION_HINT verb appears.
    # The LLM will resolve the actual capability; the gate just
    # needs to let the sentence through.
    _STATE_HINT_RE = re.compile(
        r"\b(differ|contain|contains|active|doing|left|"
        r"available|running|open|missing|changed|different|"
        r"showing|displaying|taking|using|consuming|occupying|"
        r"remaining|total|used|free|full|empty|closed|"
        r"installed|enabled|disabled|connected|disconnected|"
        r"paired|locked|unlocked|paused|stopped|playing|"
        r"downloading|uploading|streaming|recording|"
        r"status|condition|state|level|amount|size|count|"
        r"right\s+now|currently|at\s+the\s+moment)\b",
        re.IGNORECASE,
    )

    # Technical / system nouns that indicate a computer-control
    # request rather than conversational text.  Used by Check 2c
    # to disambiguate state-verb hints that appear in both
    # greetings ("how are you doing") and system queries ("what
    # are my system resources doing").
    _TECH_NOUN_RE = re.compile(
        r"\b(system|cpu|memory|disk|drive|storage|battery|"
        r"volume|screen|display|brightness|network|wifi|"
        r"bluetooth|process|processes|app|apps|application|"
        r"applications|program|programs|file|files|folder|"
        r"document|spreadsheet|workbook|page|tab|tabs|"
        r"clipboard|settings|workstation|signal|signals|"
        r"device|devices|resource|resources|server|connection|"
        r"bandwidth|speed|performance|usage|temperature|"
        r"power|charge|song|track|music|audio|video|"
        r"camera|microphone|speaker|headphones|"
        r"version|versions|data|content|contents|image|"
        r"images|text|code|report|notes|downloads|"
        r"url|website|site|web|browser|window|desktop|"
        r"column|row|rows|sheet|sheets|file|files)\b",
        re.IGNORECASE,
    )

    # Flat verb set backing the typo-tolerant near-miss test in
    # _action_verb_present. Derived from _ACTION_HINT_RE so the two
    # can never drift apart. The regex pattern is split on the
    # alternation and each alternative is reduced to bare word
    # characters, dropping the \b anchors and the grouping.
    _ACTION_VERB_SET: frozenset = frozenset(
        re.sub(r"[^a-z]", "", part.lower())
        for part in _ACTION_HINT_RE.pattern.split("|")
    ) - {""}

    # Domain vocabulary derived from the live capability registry.
    #
    # Extending a hand-written noun list to cover real requests
    # cannot be completed — it is the same trap as the verb
    # whitelist, and it is why the old gate rejected "empty the
    # Recycle Bin" and "report disk space per drive". Deriving the
    # vocabulary from the registry that actually defines the
    # capabilities makes the gate self-maintaining: a new
    # capability's own words immediately become evidence for it.
    _DOMAIN_VOCAB: Optional[frozenset] = None
    _DOMAIN_VOCAB_LOCK = threading.Lock()

    # Small talk that must never be sent to the LLM. Kept tiny and
    # explicit on purpose: a long blocklist is the failure mode
    # this gate was rebuilt to avoid. The model answers null for
    # anything that slips through, so a false pass costs latency,
    # not correctness.
    _SMALL_TALK_RE = re.compile(
        r"^\s*(hi|hey|hello|yo|thanks|thank\s+you|ok|okay|"
        r"cool|nice|great|good\s+morning|good\s+night|"
        r"how\s+are\s+you|what\s+is\s+the\s+capital|"
        r"who\s+are\s+you|what\s+can\s+you\s+do)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _domain_vocab(cls) -> frozenset:
        """Significant words from the registered capabilities."""

        with cls._DOMAIN_VOCAB_LOCK:
            if cls._DOMAIN_VOCAB is not None:
                return cls._DOMAIN_VOCAB

            vocab: set = set()
            try:
                from .capability_registry import CapabilityRegistry

                for capability in CapabilityRegistry.all():
                    category = str(
                        getattr(
                            capability.category,
                            "value",
                            capability.category,
                        )
                    )
                    vocab.add(category)

                    for token in re.split(
                        r"[^A-Za-z]+", capability.capability_id
                    ):
                        if len(token) >= 4:
                            vocab.add(token.lower())

                    for token in re.findall(
                        r"[A-Za-z]{4,}", capability.description or ""
                    ):
                        vocab.add(token.lower())
            except Exception:
                vocab = set()

            vocab.discard("")
            cls._DOMAIN_VOCAB = frozenset(vocab)
            return cls._DOMAIN_VOCAB

    @classmethod
    def reset_domain_vocab(cls) -> None:
        """Drop the cached vocabulary (after a registry change)."""

        with cls._DOMAIN_VOCAB_LOCK:
            cls._DOMAIN_VOCAB = None

    # Verbs that are too common in ordinary English to count as
    # evidence of a computer request on their own. "you make me
    # happy" and "we should set up a meeting" are conversation, not
    # OS commands, and both were let through when any listed verb
    # counted. A generic verb only supports a decision when real
    # computer-domain evidence is also present.
    _GENERIC_VERBS: frozenset = frozenset({
        "add", "arrange", "change", "check", "close", "compute",
        "condense", "display", "drop", "end", "fetch", "find",
        "fix", "get", "give", "go", "group", "jot", "list", "load",
        "make", "prepare", "pull", "put", "rank", "read", "reveal",
        "save", "send", "set", "show", "start", "stop", "take",
        "tell", "total", "use", "verify", "write",
    })

    @staticmethod
    def _has_specific_action_verb(text: str) -> bool:
        """An unambiguous computer-action verb appears in the text."""

        if not LLMIntentResolver._ACTION_HINT_RE.search(text):
            words = re.findall(r"[a-z']+", text.lower())
            for word in words:
                if len(word) < 4:
                    continue
                for verb in LLMIntentResolver._ACTION_VERB_SET:
                    if (
                        verb in LLMIntentResolver._GENERIC_VERBS
                        or abs(len(word) - len(verb)) > 1
                    ):
                        continue
                    if difflib.SequenceMatcher(
                        None, word, verb
                    ).ratio() >= 0.75:
                        return True
            return False

        for word in re.findall(r"[a-z']+", text.lower()):
            if (
                word in LLMIntentResolver._ACTION_VERB_SET
                and word not in LLMIntentResolver._GENERIC_VERBS
            ):
                return True
        return False

    @staticmethod
    def _has_domain_evidence(text: str) -> bool:
        """
        Real computer-domain evidence.

        Either an explicit technical noun, or any word the
        capability registry itself uses. Deriving the vocabulary
        from the registry is what makes this self-maintaining: a new
        capability's own words immediately become evidence for it,
        so nobody has to keep editing a noun list.
        """

        if LLMIntentResolver._TECH_NOUN_RE.search(text):
            return True

        vocab = LLMIntentResolver._domain_vocab()
        if not vocab:
            return False

        for token in re.findall(r"[a-z]{4,}", text.lower()):
            if token in vocab:
                return True

        # Deliberately NO fuzzy vocabulary matching here. It was
        # tried and removed: it produced only false positives
        # ("control my computer" matched the vocab entries
        # "controls" and "compute" at ratio 0.93) while adding
        # nothing, because every real held-out request already
        # matches an exact vocabulary word. Typo tolerance is
        # applied to the action-verb check instead, where a
        # misspelling is unambiguous.
        return False

    # Tiers returned by lexical_actionability.
    ACTIONABLE = "actionable"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"

    @classmethod
    def lexical_actionability(cls, text: str) -> str:
        """
        Classify a request on the three tiers that actually matter.

        BLOCKED   positive evidence of non-actionable text: narration,
                  a greeting, small talk. Never sent to the model.
        ACTIONABLE real lexical evidence of a computer request.
        AMBIGUOUS neither, and in particular no HARD evidence of
                  conversation either.

        The AMBIGUOUS tier exists because a boolean gate cannot
        express it, and that ambiguity is the whole problem.
        MEASURED: these two requests produce byte-identical signals
        on every lexical probe available here (domain evidence,
        specific action verb, state hint, small talk) — all four
        False for both — yet one is a real command and the other is
        ordinary conversation:

            "i need this written out somewhere durable"  document.create_txt
            "that genuinely cheered me up"          conversation

        No boolean function of those probes can separate them, so
        a boolean gate must either lose the real request or admit
        the conversation. Returning a third value lets the caller
        escalate to SEMANTIC evidence instead of guessing. This is
        not a new vocabulary; it is the existing probes, asked
        whether they are sure.
        """

        if not (
            text
            and isinstance(text, str)
            and len(text.split()) >= 2
        ):
            return cls.BLOCKED

        lowered = text.lower()

        # Narration guard: third-person past narration is
        # description, not a request ("she set the table before we
        # arrived"). Both signals are required, because "how are
        # you doing" contains a pronoun but is a greeting.
        if re.match(
            r"^\s*(she|he|they|we)\s+", lowered
        ) and re.search(
            r"\b(before|after|when|while|yesterday|last|ago|"
            r"earlier|prior|since|during)\b",
            lowered,
        ):
            return cls.BLOCKED

        if cls._has_domain_evidence(lowered):
            return cls.ACTIONABLE

        if cls._has_specific_action_verb(lowered):
            return cls.ACTIONABLE

        # A state hint on its own is not enough. "hi how are you
        # doing today" contains one and is a greeting; the old
        # implementation required a state hint AND a technical
        # noun together, which is the right rule and is preserved
        # by only honouring state hints once domain evidence exists.
        if cls._STATE_HINT_RE.search(lowered):
            return cls.BLOCKED

        if cls._SMALL_TALK_RE.match(lowered):
            return cls.BLOCKED

        return cls.AMBIGUOUS

    @staticmethod
    def looks_actionable(text) -> bool:
        """
        Cheap LEXICAL gate: is there positive evidence of a computer
        request?

        This remains a cost optimisation, never a semantic
        authority. It reports True only for the ACTIONABLE tier, so
        the AMBIGUOUS tier still returns False here; callers that can
        escalate should consult lexical_actionability and then
        grounded_capability rather than this predicate alone.
        """

        return (
            LLMIntentResolver.lexical_actionability(text)
            == LLMIntentResolver.ACTIONABLE
        )

    # =========================================================
    # PUBLIC API
    # =========================================================

    # -------------------------------------------------------------
    # SEMANTIC GROUNDING
    # -------------------------------------------------------------
    # The lexical gate cannot distinguish conversation from an
    # indirect command (proved: identical probes on both). The
    # fix is not more vocabulary, it is to escalate to semantic
    # evidence when the lexical tier is AMBIGUOUS, and then require
    # the model to SHOW ITS WORK.
    #
    # The model must return, alongside its choice, a verbatim span
    # of the request that establishes the request is asking for a
    # registered capability. That span is then verified against the
    # request itself. A hallucinated grounding fails; an invented
    # capability id fails; a blocked capability fails. Nothing here
    # is a keyword list.

    # Words that cannot constitute grounding on their own. Function
    # words and bare pronouns: if the model's whole justification
    # reduces to these, it has not actually grounded anything.
    _GROUNDING_STOPWORDS: frozenset = frozenset({
        "the", "a", "an", "and", "or", "but", "if", "then",
        "of", "to", "in", "on", "at", "by", "for", "with",
        "from", "into", "onto", "over", "under", "about",
        "that", "this", "these", "those", "it", "its", "them",
        "me", "my", "mine", "you", "your", "yours", "he", "she",
        "we", "us", "our", "they", "them", "their", "is", "are",
        "was", "were", "be", "been", "being", "do", "does", "did",
        "can", "could", "will", "would", "shall", "should", "may",
        "might", "must", "have", "has", "had", "so", "just", "very",
        "some", "any", "all", "more", "most", "much", "please",
        "now", "here", "there", "what", "when", "where", "which",
        "who", "how", "why", "one", "thing", "stuff",
    })

    @staticmethod
    def _normalise_for_fidelity(text: str) -> str:
        """Collapse a span to comparable word tokens."""
        return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()

    @classmethod
    def evaluate_grounding(
        cls,
        request: str,
        capability_id: Optional[str],
        anchor: str,
        target: Optional[str] = None,
        application: Optional[str] = None,
        lexical_tier: str = AMBIGUOUS,
        prior_turn: Optional[str] = None,
    ) -> "GroundingResult":
        """
        Produce the reusable semantic grounding verdict.

        Consumes evidence the system already produces rather than
        inventing new contracts:

          * the registry descriptor, for domain, category, operation,
            declared inputs and risk tier,
          * ``ExecutionSafety``, for policy and confirmation,
          * ``CapabilityResolver``, which must independently agree and
            whose confidence and typed evidence are carried through,
          * ``SELECTION_BOUNDARIES``, for the relevance figure.

        See ``GroundingResult`` for why fidelity and substance are
        hard gates and why relevance is not.

        ``prior_turn`` is the Phase 3 Item 4 context channel. It is
        OPTIONAL and defaults to ``None``, in which case every
        computation below is byte-identical to before it existed.
        """

        from .capabilities import SELECTION_BOUNDARIES
        from .capability_registry import CapabilityRegistry
        from .execution_safety import ExecutionSafety
        from .capability_resolution import (
            CapabilityResolutionEvidence,
            CapabilityResolutionStatus,
            GroundingResult,
        )

        reasons: List[str] = []
        evidence: List[CapabilityResolutionEvidence] = []

        # A prior turn only counts as context when it is a non-empty
        # string. Anything else (None, "", whitespace) is treated as
        # absent, so a caller cannot accidentally widen the grounding
        # gate by passing a blank string.
        prior = (
            str(prior_turn).strip()
            if isinstance(prior_turn, str) and str(prior_turn).strip()
            else None
        )

        if not isinstance(capability_id, str) or not capability_id.strip():
            return GroundingResult(
                grounded=False,
                lexical_tier=lexical_tier,
                reasons=("no candidate capability was proposed",),
            )

        # ---- anchor fidelity -------------------------------------
        normalised_anchor = cls._normalise_for_fidelity(anchor)
        normalised_request = cls._normalise_for_fidelity(request)

        if not normalised_anchor:
            reasons.append("no grounding span was provided")
            return GroundingResult(
                grounded=False,
                lexical_tier=lexical_tier,
                capability_id=capability_id,
                reasons=tuple(reasons),
            )

        fidelity = (
            normalised_anchor in normalised_request
            if normalised_request
            else False
        )
        if not fidelity:
            reasons.append(
                "grounding span is not present in the request"
            )

        # ---- anchor substance ------------------------------------
        anchor_tokens = [
            token
            for token in normalised_anchor.split()
            if token and token not in cls._GROUNDING_STOPWORDS
        ]
        substance = bool(anchor_tokens)
        if not substance:
            reasons.append(
                "grounding span contains no content word"
            )

        # ---- discriminativeness --------------------------------
        # Faithfulness is not discriminativeness. A span covering the
        # whole request is verbatim for EVERY candidate, so it cannot
        # tell this capability apart from any other.
        #
        # MEASURED: a vague request whose specific anchor correctly
        # failed grounding was accepted at full strength when the
        # model quoted the entire request back. That inverts the
        # contract — the vaguer the request, the easier it was to
        # "ground".
        #
        # The rule is structural, not a phrase blacklist: grounding
        # must leave at least one content word of the request outside
        # the anchor.
        #
        # ---- ITEM 4, PRIOR-TURN CHANNEL -------------------------
        # With a prior turn supplied, the unit of evidence is the
        # DISCOURSE, not the bare request. That is forced by
        # measurement, not preference: against all 8 sealed v4
        # context items the model returned an anchor covering the
        # ENTIRE current request in 8/8 cases, because a pronoun-led
        # request has no honest narrower span. The
        # discriminating information genuinely lives in the prior
        # turn, so when one is supplied the denominator becomes the
        # request plus the prior turn.
        #
        # FIDELITY IS DELIBERATELY NOT RELAXED. The anchor must still
        # be verbatim in the CURRENT REQUEST. Measured 8/8 the model
        # satisfies this anyway, so allowing prior-turn anchors would
        # buy nothing and would cost the guarantee that the model is
        # pointing at words the user just typed.
        #
        # KNOWN, ACCEPTED NARROWING: with a prior turn present, a
        # model that names the wrong capability and quotes the whole
        # request can still pass this check, because the prior turn
        # supplies the out-of-anchor content word. Closing that would
        # require verifying the capability against the prior turn
        # (per-capability verifiers, or a model-side agreement
        # check), which is beyond this item. It cannot arise when no
        # prior turn is supplied: the rule below is then unchanged.
        # See PHASE_3_CLOSEOUT_FINAL_2026-10-02.md section 10.
        request_tokens = [
            token
            for token in normalised_request.split()
            if token and token not in cls._GROUNDING_STOPWORDS
        ]
        if prior is not None:
            normalised_prior = cls._normalise_for_fidelity(prior)
            request_tokens = request_tokens + [
                token
                for token in normalised_prior.split()
                if (token
                    and token not in cls._GROUNDING_STOPWORDS
                    and token not in set(request_tokens))
            ]
        discriminative = bool(
            set(request_tokens) - set(anchor_tokens)
        )
        if not discriminative:
            reasons.append(
                "grounding span covers the whole request and so "
                "discriminates nothing"
            )

        evidence.append(
            CapabilityResolutionEvidence(
                match_type="semantic_grounding_anchor",
                score=(
                    1.0
                    if (fidelity and substance and discriminative)
                    else 0.0
                ),
                reason=(
                    "Quoted span is verbatim in the request, carries "
                    "a content word, and is narrower than the request."
                    if (fidelity and substance and discriminative)
                    else "; ".join(reasons)
                ),
            )
        )

        # ---- validity + descriptor facts ------------------------
        try:
            descriptor = CapabilityRegistry.get(capability_id)
        except Exception:
            descriptor = None

        if descriptor is None:
            reasons.append(
                "candidate is not a registered capability"
            )
            return GroundingResult(
                grounded=False,
                lexical_tier=lexical_tier,
                capability_id=capability_id,
                anchor=normalised_anchor,
                fidelity=fidelity,
                substance=substance,
                discriminative=discriminative,
                reasons=tuple(reasons),
                evidence=tuple(evidence),
            )

        category = getattr(
            descriptor.category, "value", descriptor.category
        )
        domain = str(capability_id).split(".", 1)[0]
        declared_inputs = tuple(
            sorted(getattr(descriptor, "supported_inputs", ()) or ())
        )

        # ---- policy ------------------------------------------------
        # Both existing policy contracts are consulted, neither is
        # replaced. ExecutionSafety decides whether the operation may
        # be considered at all; the agent-framework adapter owns the
        # human-approval token gate for high/critical capabilities.
        # Grounding consults both and carries the verdict forward, so
        # a grounded decision cannot launder a gated capability into
        # an ordinary one.
        try:
            safety = ExecutionSafety.check(capability_id)
            policy_allowed = bool(safety.allowed)
        except Exception:
            policy_allowed = False

        requires_confirmation = False
        try:
            from .agent_framework_adapter import (
                requires_approval_token,
            )
            requires_confirmation = bool(
                requires_approval_token(capability_id)
            )
        except Exception:
            requires_confirmation = False

        if not policy_allowed:
            reasons.append(
                "policy or safety does not permit this capability"
            )

        # ---- existing resolver must independently agree ----------
        confidence = 0.0
        status = None
        alternatives: Tuple[str, ...] = ()
        try:
            from .capability_resolver import CapabilityResolver

            resolution = CapabilityResolver().resolve_operation(
                capability_id,
                description=request,
                inputs=declared_inputs,
            )
            confidence = float(getattr(resolution, "confidence", 0.0) or 0.0)
            status = getattr(
                getattr(resolution, "status", None), "value", None
            )
            for item in getattr(resolution, "evidence", ()) or ():
                try:
                    evidence.append(item)
                except Exception:
                    continue
            alternatives = tuple(
                str(getattr(alt, "capability_id", alt))
                for alt in getattr(resolution, "alternatives", ())
                or ()
            )
        except Exception:
            confidence = 0.0
            status = None

        if status != CapabilityResolutionStatus.RESOLVED.value:
            reasons.append(
                "the capability resolver did not confirm the candidate"
            )

        # ---- relevance (reported, never required) ----------------
        relevance = 0.0
        vocabulary = {
            token
            for token in re.split(r"[^A-Za-z]+", str(capability_id))
            if len(token) >= 3
        }
        vocabulary.update(
            token
            for token in re.split(r"[^A-Za-z]+", str(category))
            if len(token) >= 3
        )
        vocabulary.update(
            re.findall(r"[A-Za-z]{3,}", descriptor.description or "")
        )
        note = SELECTION_BOUNDARIES.get(capability_id)
        if note:
            vocabulary.update(re.findall(r"[A-Za-z]{3,}", note))

        vocabulary = {
            token.lower() for token in vocabulary
        } - cls._GROUNDING_STOPWORDS

        if anchor_tokens and vocabulary:
            hits = [
                token for token in anchor_tokens
                if token in vocabulary
            ]
            relevance = round(len(hits) / len(anchor_tokens), 3)

        evidence.append(
            CapabilityResolutionEvidence(
                match_type="grounding_relevance",
                score=relevance,
                reason=(
                    "Span/capability vocabulary overlap. Informational "
                    "only: an indirect request may legitimately share "
                    "no vocabulary with the description."
                ),
            )
        )

        grounded = bool(
            fidelity
            and substance
            and discriminative
            and policy_allowed
            and status == CapabilityResolutionStatus.RESOLVED.value
        )

        return GroundingResult(
            grounded=grounded,
            lexical_tier=lexical_tier,
            capability_id=capability_id,
            domain=domain,
            category=str(category),
            operation=str(getattr(descriptor, "operation", "") or ""),
            anchor=normalised_anchor,
            fidelity=fidelity,
            substance=substance,
            discriminative=discriminative,
            relevance=relevance,
            confidence=confidence,
            declared_inputs=declared_inputs,
            target=target,
            application=application,
            risk_level=getattr(descriptor, "risk_level", None),
            requires_confirmation=requires_confirmation,
            policy_allowed=policy_allowed,
            status=status,
            alternatives=alternatives,
            evidence=tuple(evidence),
            reasons=tuple(reasons),
        )

    @classmethod
    def grounding_evidence(
        cls,
        request: str,
        capability_id: str,
        anchor: str,
    ) -> Dict[str, Any]:
        """
        Backwards-compatible dict view of evaluate_grounding().
        """
        return cls.evaluate_grounding(
            request, capability_id, anchor
        ).to_dict()

    @staticmethod
    def _prior_turn_block(prior_turn: Optional[str]) -> str:
        """The optional prior-turn prompt section.

        ITEM 4. Returns the EMPTY STRING when there is no usable prior
        turn, so the composed prompt is byte-identical to the
        pre-Item-4 prompt. A blank or whitespace-only string is
        treated as absent, so a caller cannot widen the prompt (or
        the grounding gate) by passing "".
        """
        prior = (
            str(prior_turn).strip()
            if isinstance(prior_turn, str) and str(prior_turn).strip()
            else None
        )
        if prior is None:
            return ""
        return f"PREVIOUS TURN: {prior}\n\n"

    def _grounding_probe(
        self,
        text: str,
        deadline: float,
        prior_turn: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Ask the model to classify and ground, in one call.

        Reuses the existing backend order, per-call timeout,
        total budget, in-flight slot accounting, shortlist catalog
        and JSON extraction. It is a probe, not a second selector:
        it cannot execute anything, and everything it returns is
        re-validated against the registry and the safety layer
        before use.

        ITEM 4: ``prior_turn`` adds a clearly labelled PREVIOUS TURN
        section and one extra rule teaching the model to resolve
        references like "that" / "it" against it. When it is None the
        prompt is byte-identical to the pre-Item-4 prompt: the rules
        branch selects the original wording and the context section
        is the empty string.
        """

        catalog = self._shortlist_catalog()
        context = self._prior_turn_block(prior_turn)
        prior_supplied = bool(context)

        rules = (
            "Rules:\n"
            "1. If the user is talking, joking, asking a "
            "knowledge question, requesting creative writing, "
            "or asking for advice, reply actionable=false.\n"
            "2. If the user wants the assistant to perform an "
            "action on their computer, device, files, "
            "applications or accounts, reply actionable=true "
            "and give the single best capability id.\n"
        )
        if prior_supplied:
            rules += (
                "3. Quote a span of the user's CURRENT REQUEST "
                "VERBATIM that shows why. Copy it exactly, including "
                "the user's own spelling. Do not paraphrase, do not "
                "translate, do not invent words that are not there. "
                "Never quote from the PREVIOUS TURN.\n"
                "4. If the request is indirect or informal, still "
                "answer true if it genuinely asks for a computer "
                "action.\n"
                "5. The CURRENT REQUEST may refer back to the "
                "PREVIOUS TURN with a word like \"that\", \"it\" or "
                "\"this one\". When it does, resolve the reference "
                "against the PREVIOUS TURN and name the capability "
                "the referent implies.\n\n"
            )
        else:
            rules += (
                "3. Quote a span of the user's message VERBATIM that "
                "shows why. Copy it exactly, including the user's own "
                "spelling. Do not paraphrase, do not translate, do not "
                "invent words that are not there.\n"
                "4. If the request is indirect or informal, still "
                "answer true if it genuinely asks for a computer "
                "action.\n\n"
            )

        reply_format = (
            'Reply ONLY with JSON: {"actionable": true|false, '
            '"capability_id": "<id or null>", '
            '"anchor": "<verbatim span or null>"}\n\n'
        )

        prompt = (
            "You are deciding whether a user is asking an "
            "assistant to CONTROL A COMPUTER, or merely talking.\n\n"
            f"CAPABILITY INDEX:\n{catalog}\n\n"
            f"{rules}{reply_format}{context}"
            f"USER: {text}\n\n"
            "JSON:"
        )

        for mode in self._backend_modes():
            if time.monotonic() >= deadline:
                return None
            try:
                raw = self._call_llm_with_timeout(
                    prompt, mode=mode
                )
            except Exception:
                continue
            if not isinstance(raw, str):
                continue
            parsed = self._extract_json(raw)
            if isinstance(parsed, list) and parsed:
                parsed = parsed[0]
            if not isinstance(parsed, dict):
                continue
            return parsed
        return None

    def grounded_capability(
        self,
        text: str,
        target: Optional[str] = None,
        application: Optional[str] = None,
        require_ambiguous_tier: bool = True,
        prior_turn: Optional[str] = None,
    ) -> Optional["GroundingResult"]:
        """
        Semantic grounding check for a lexically AMBIGUOUS request.

        Returns a GroundingResult only when the semantic grounding
        contract holds: the model committed to actionable, named a
        registered capability, quoted a verbatim span of the request,
        that span carries a content word, policy permits the route,
        and the existing CapabilityResolver independently agrees.

        Returns None for ordinary conversation, including when the
        model hallucinates a capability. No Level 3 action is invented
        without checkable evidence.

        `require_ambiguous_tier` is True for the ordinary escalation
        path, which only ever fires on lexically ambiguous wording.
        Cross-domain arbitration sets it False because arbitration IS
        the ambiguous-wording case and it must be able to reach the
        probe even when a deterministic candidate was already found.
        Every other condition of the contract is unchanged, so
        lifting this one restriction cannot admit text that grounding
        would otherwise reject.

        ITEM 4: ``prior_turn`` is the optional context channel. When
        None, every step below is identical to before.
        """

        from .capability_resolution import GroundingResult

        tier = self.lexical_actionability(text)
        if require_ambiguous_tier and tier != self.AMBIGUOUS:
            return None

        deadline = time.monotonic() + self._RESOLVE_TOTAL_BUDGET
        # ITEM 4: the prior turn is forwarded only when supplied, so
        # the no-prior call is literally the pre-Item-4 call and an
        # existing `_grounding_probe` override with the old signature
        # keeps working unchanged.
        parsed = self._grounding_probe(
            text,
            deadline,
            **({"prior_turn": prior_turn} if prior_turn else {}),
        )
        if not isinstance(parsed, dict):
            return None

        if parsed.get("actionable") is not True:
            return None

        raw_operation = parsed.get("capability_id")
        operation = None
        if isinstance(raw_operation, str) and raw_operation.strip():
            operation = self._canonical_operation(
                raw_operation.strip().lower()
            )

        anchor = parsed.get("anchor")

        result = self.evaluate_grounding(
            text,
            operation,
            anchor if isinstance(anchor, str) else "",
            target=target,
            application=application,
            lexical_tier=tier,
            prior_turn=prior_turn,
        )

        if not result.grounded:
            return None
        return result

    def arbitration_probe(
        self,
        text: str,
        deterministic_capability: str,
        semantic_capability: str,
        deadline: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Capability-first comparison of two REGISTERED capabilities.

        Both sides are named capabilities carrying their registry
        descriptor and their existing SELECTION_BOUNDARIES note. No
        phrase is ever shown as a candidate, and neither domain is
        privileged: the same prompt is used whether the two
        capabilities share a domain or not, which is what makes this
        cross-domain by construction rather than by a rule.

        Reuses the existing backend order, per-call timeout, total
        budget, in-flight slot accounting and JSON extraction.
        """

        prompt = (
            "Two Genesis OS capabilities are candidates for one "
            "user request. Choose the ONE that better expresses "
            "what the user wants done.\n\n"
            f"CANDIDATE A:\n{self._describe_for_choice(deterministic_capability)}\n\n"
            f"CANDIDATE B:\n{self._describe_for_choice(semantic_capability)}\n\n"
            "Rules:\n"
            "1. Answer exactly one of A or B, whichever matches the "
            "user's actual intent better.\n"
            "2. Quote a span of the user's request, VERBATIM, that "
            "justifies your choice. Copy it exactly; do not "
            "paraphrase or invent words.\n"
            "3. If genuinely neither, set choice to null.\n\n"
            'Reply ONLY: {"choice": "A"|"B"|null, '
            '"anchor": "<span>"}\n\n'
            f"USER REQUEST: {text}\n\n"
            "JSON:"
        )

        for mode in self._backend_modes():
            if time.monotonic() >= deadline:
                return None
            try:
                raw = self._call_llm_with_timeout(
                    prompt, mode=mode
                )
            except Exception:
                continue
            if not isinstance(raw, str):
                continue
            parsed = self._extract_json(raw)
            if isinstance(parsed, list) and parsed:
                parsed = parsed[0]
            if isinstance(parsed, dict):
                return parsed
        return None

    @staticmethod
    def _describe_for_choice(capability_id: str) -> str:
        """Descriptor + existing boundary note for one capability."""
        try:
            from .capability_registry import CapabilityRegistry
            from .capabilities import SELECTION_BOUNDARIES

            descriptor = CapabilityRegistry.get(capability_id)
        except Exception:
            return f"{capability_id} (unregistered)"
        parts = [capability_id, f"[{descriptor.risk_level}]"]
        inputs = sorted(descriptor.supported_inputs or ())
        if inputs:
            parts.append(f"in=({','.join(inputs)})")
        parts.append(f"- {descriptor.description}")
        note = SELECTION_BOUNDARIES.get(capability_id)
        if note:
            parts.append(f"BOUNDARY: {note}")
        return " ".join(parts)

    @classmethod
    def _deterministic_evidence(
        cls,
        decision: Dict[str, Any],
        capability_id: str,
    ) -> Dict[str, Any]:
        """
        Capture the evidence that ALREADY exists for a deterministic
        candidate.

        Nothing is invented. Fields the decision does not carry stay
        at their default rather than being filled with an optimistic
        constant. This replaces a previous version that asserted a
        single fabricated "authoritative, score 1.0" entry, which
        made a deterministic candidate look better evidenced than it
        was and hid exactly what the arbitration needed to compare.

        Returns a plain dict with the captured facts plus typed
        CapabilityResolutionEvidence entries for the resolver's own
        verdict on that capability.
        """

        from .capability_resolution import (
            CapabilityResolutionEvidence,
        )

        parameters = decision.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        resolution = parameters.get("_capability_resolution")
        resolution = (
            resolution if isinstance(resolution, dict) else {}
        )

        target = decision.get("target")
        application = decision.get("application")
        anchored = bool(target or application)

        descriptor = None
        declared_inputs: tuple = ()
        risk_level = None
        domain = capability_id.split(".", 1)[0]
        operation = capability_id
        try:
            from .capability_registry import CapabilityRegistry

            descriptor = CapabilityRegistry.get(capability_id)
            declared_inputs = tuple(
                sorted(getattr(descriptor, "supported_inputs", ()) or ())
            )
            risk_level = getattr(descriptor, "risk_level", None)
            operation = str(getattr(descriptor, "operation", "") or "")
        except Exception:
            descriptor = None

        confidence = decision.get("confidence")
        confidence = (
            float(confidence)
            if isinstance(confidence, (int, float))
            else 0.0
        )

        evidence = [
            CapabilityResolutionEvidence(
                match_type="deterministic_candidate",
                score=confidence,
                reason=(
                    "Deterministic detector match"
                    + (" anchored by a named target or application"
                       if anchored else " with no named target")
                ),
            ),
        ]

        # The existing resolver's verdict on this same capability,
        # carried through rather than restated.
        for item in resolution.get("evidence", []) or []:
            try:
                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type=str(item.get("match_type")),
                        score=float(item.get("score", 0.0) or 0.0),
                        reason=str(item.get("reason", "")),
                    )
                )
            except Exception:
                continue

        approval_required = False
        try:
            from .agent_framework_adapter import (
                requires_approval_token,
            )
            approval_required = bool(
                requires_approval_token(capability_id)
            )
        except Exception:
            approval_required = False

        return {
            "capability_id": capability_id,
            "domain": domain,
            "operation": operation,
            "confidence": confidence,
            "anchored": anchored,
            "target": target,
            "application": application,
            "declared_inputs": declared_inputs,
            "risk_level": risk_level,
            "approval_required": approval_required,
            "status": resolution.get("status"),
            "alternatives": tuple(
                str(item.get("capability_id"))
                for item in resolution.get("alternatives", []) or []
                if isinstance(item, dict)
            ),
            "evidence": tuple(evidence),
        }

    def arbitrate_capabilities(
        self,
        text: str,
        deterministic_decision: Dict[str, Any],
        grounding: "GroundingResult",
    ) -> "ArbitrationResult":
        """
        Compare a deterministic candidate with a semantically
        grounded candidate and return a structured verdict.

        Order of decision, cheapest and most conservative first:

          1. No meaningful challenge        -> DETERMINISTIC
          2. Challenger not admissible      -> DETERMINISTIC
          3. Same capability on both sides  -> agreement, no override
          4. Challenger cannot justify a
             DISCRIMINATIVE span           -> DETERMINISTIC
          5. Otherwise compare the two named capabilities and keep
             whichever better expresses the request; abstention,
             a missing verdict or an unfaithful quote all resolve to
             DETERMINISTIC.

        risk_level is NEVER used as a relevance signal. A lower-risk
        capability is not thereby the more correct one, and treating
        it as one would silently bias arbitration toward whichever
        domain happens to be least dangerous. Neither is
        `deterministic_strength > semantic_strength`: a bare numeric
        comparison cannot express appropriateness, which is what the
        capability-first comparison in step 5 exists to judge.

        Nothing here executes anything; the result only chooses a
        validated capability id.
        """

        from .capability_resolution import (
            ArbitrationResult,
            CapabilityResolutionEvidence,
            GroundingResult,
        )

        decision = (
            deterministic_decision
            if isinstance(deterministic_decision, dict)
            else {}
        )
        deterministic_capability = decision.get("intent")
        if not isinstance(deterministic_capability, str) or "." not in (
            deterministic_capability
        ):
            deterministic_capability = None

        det = self._deterministic_evidence(
            decision, deterministic_capability or ""
        )

        def _result(selected, reason, outcome, **extra):
            payload = {
                "selected": selected,
                "selected_source": (
                    "deterministic"
                    if selected == "deterministic"
                    else "semantic"
                ),
                "outcome": outcome,
                "arbitration_occurred": True,
                "deterministic_capability": (
                    det.get("capability_id") or None
                ),
                "semantic_capability": getattr(
                    grounding, "capability_id", None
                ),
                "reason": reason,
                "deterministic_confidence": det.get("confidence", 0.0),
                "semantic_confidence": getattr(
                    grounding, "confidence", 0.0
                ),
                "deterministic_anchored": det.get("anchored", False),
                "approval_required": bool(
                    det.get("approval_required")
                ),
                "deterministic_evidence": det.get("evidence", ()),
                "policy_allowed": True,
            }
            payload.update(extra)
            return ArbitrationResult(**payload)

        # ---- 1/2. challenger admissibility ---------------------
        if not getattr(grounding, "grounded", False):
            return _result(
                "deterministic",
                "semantic candidate is not grounded", "rejected",
            )

        if deterministic_capability is None:
            return _result(
                "deterministic",
                "no deterministic candidate to arbitrate against",
                "inconclusive",
            )

        # ---- 3. agreement -------------------------------------
        if grounding.capability_id == deterministic_capability:
            return _result(
                "deterministic",
                "both candidates agree; no arbitration needed",
                "agreement",
            )

        # ---- 4. discriminative grounding ----------------------
        if not getattr(grounding, "discriminative", False):
            return _result(
                "deterministic",
                "semantic grounding does not discriminate this "
                "capability from any other",
                "rejected",
            )

        # Policy is re-checked at arbitration time, never inherited.
        policy_ok = True
        try:
            from .execution_safety import ExecutionSafety

            policy_ok = bool(
                ExecutionSafety.check(
                    grounding.capability_id
                ).allowed
            )
        except Exception:
            policy_ok = False
        if not policy_ok:
            return _result(
                "deterministic",
                "semantic candidate is not permitted by policy",
                "rejected",
                policy_allowed=False,
            )

        # ---- 5. capability-first comparison --------------------
        deadline = time.monotonic() + self._RESOLVE_TOTAL_BUDGET
        verdict = self.arbitration_probe(
            text, deterministic_capability,
            grounding.capability_id, deadline,
        )
        if not isinstance(verdict, dict):
            return _result(
                "deterministic",
                "arbitration produced no verdict", "inconclusive",
            )

        choice = verdict.get("choice")
        anchor = verdict.get("anchor")
        anchor = anchor if isinstance(anchor, str) else ""
        semantic_anchor = (
            anchor.strip() if isinstance(anchor, str) else ""
        )

        faithful = bool(
            self._normalise_for_fidelity(semantic_anchor)
        ) and (
            self._normalise_for_fidelity(semantic_anchor)
            in self._normalise_for_fidelity(text)
        )

        comparison_evidence = CapabilityResolutionEvidence(
            match_type="arbitration_choice",
            score=1.0 if choice in ("A", "B") else 0.0,
            reason=(
                f"Capability-first comparison selected {choice!r}."
            ),
        )

        shared = {
            "semantic_anchor": semantic_anchor,
            "anchor_faithful": faithful,
            "semantic_grounded": True,
            "semantic_evidence": (comparison_evidence,),
            "semantic_strength": float(
                getattr(grounding, "strength", 0.0) or 0.0
            ),
        }

        if choice not in ("A", "B"):
            return _result(
                "deterministic",
                "comparison abstained; deterministic candidate retained",
                "abstained",
                **shared,
            )

        if not faithful:
            return _result(
                "deterministic",
                "comparison chose the semantic candidate but its "
                "justification is not verbatim in the request",
                "rejected",
                **shared,
            )

        if choice == "A":
            return _result(
                "deterministic",
                "comparison judged the deterministic candidate the "
                "better expression of the request",
                "deterministic_preferred",
                **shared,
            )

        return _result(
            "semantic",
            "cross-domain arbitration: the semantic candidate better "
            "expresses the request and is anchored in the user's own "
            "words",
            "semantic_preferred",
            risk_level=getattr(grounding, "risk_level", None),
            **shared,
        )

    # Per-domain vocabulary derived from the live registry: the
    # capability ids and descriptions of that domain's capabilities.
    #
    # This exists because the arbitration trigger needs to know
    # whether a request names the domain the deterministic answer
    # belongs to, or a different one. It is derived from the
    # registry, so a new capability teaches the gate its own
    # vocabulary; there is no hand-written noun list.
    #
    # MEASURED REJECTION that shaped this. A "top scoring domain"
    # rule was tried and failed: domain vocabularies differ in size
    # by more than 15x (browser 61 terms, time 4), so a single
    # incidental hit in a small domain outranked every genuine hit in
    # a large one, and "write hello world" scored highest for `time`
    # via the word "world". Counting is therefore never compared
    # across domains; only PRESENCE is used.
    _DOMAIN_TOKENS: Optional[dict] = None
    _DOMAIN_TOKENS_LOCK = threading.Lock()

    @classmethod
    def domain_tokens(cls) -> dict:
        """domain -> frozenset of that domain's registry vocabulary."""
        with cls._DOMAIN_TOKENS_LOCK:
            if cls._DOMAIN_TOKENS is not None:
                return cls._DOMAIN_TOKENS

            tokens: dict = {}
            try:
                from .capability_registry import CapabilityRegistry

                for capability in CapabilityRegistry.all():
                    domain = capability.capability_id.split(
                        ".", 1
                    )[0]
                    # CAPABILITY-ID TOKENS ONLY, never description
                    # prose. Descriptions cross-contaminate domains
                    # and were measured to defeat this: "folder"
                    # appears in a file.* description and "bring" in
                    # an application.* one, which made both real
                    # cross-domain cases look like their own domain.
                    # Id tokens are unambiguous: "folder" belongs to
                    # the folder domain and to no other.
                    for token in re.split(
                        r"[^A-Za-z]+", capability.capability_id
                    ):
                        if len(token) >= 3:
                            tokens.setdefault(domain, set()).add(
                                token.lower()
                            )
            except Exception:
                tokens = {}

            for domain in tokens:
                tokens[domain] = frozenset(
                    tokens[domain] - cls._GROUNDING_STOPWORDS
                )
            cls._DOMAIN_TOKENS = tokens
            return tokens

    @classmethod
    def deterministic_evidence_is_decisive(
        cls,
        text: str,
        decision: Dict[str, Any],
        capability_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Answer the RIGHT question for arbitration eligibility:

            "Is this deterministic candidate justified by THIS
             request well enough to be authoritative without a
             semantic challenge?"

        NOT the question the previous trigger asked, which was
        "are the matched domain's words absent?". Those are
        different questions, and the old one was measured to be
        the wrong boundary: a capability can be strongly
        deterministic while the request says little in its domain's
        vocabulary, and can have plenty of that vocabulary while
        being semantically ambiguous.

        WHY THE OBVIOUS SIGNALS COULD NOT BE USED. Measured:
        the detector emits confidence 0.95 for every match, and
        `CapabilityResolver.resolve_operation()` returns only
        `exact_capability_id` score 1.0 for any registered id
        regardless of the request. Neither carries per-request
        information, so neither can decide anything. Alternatives
        lists are empty on the exact-id path too.

        What DOES vary per request, and is registry-derived rather
        than hand-written:

          1. ANCHORING. A target or application was extracted from
             THIS request, so the match was read off a concrete
             object the user named.
          2. DESCRIPTOR OVERLAP. The capability's own description
             describes this request (description affinity > 0).
          3. OPERATION NAMED. The request literally names the
             action this capability performs — the capability's
             own operation token appears in the request text.

        A candidate with at least one of those is decisive and pays
        nothing. A candidate with none of them is a bare id with no
        per-request justification, and a semantic challenge is
        warranted.

        No domain is named, no domain pair is special-cased, and no
        vocabulary is introduced: every term comes from the
        capability's own registry descriptor.

        Returns {"decisive": bool, "signals": {...},
                 "reasons": [...]}.
        """

        signals = {
            "anchored": False,
            "descriptor_overlap": False,
            "operation_named": False,
            "confidence": 0.0,
        }

        if not isinstance(decision, dict):
            return {
                "decisive": False,
                "signals": signals,
                "reasons": ("no deterministic decision to judge",),
            }

        confidence = decision.get("confidence")
        signals["confidence"] = (
            float(confidence)
            if isinstance(confidence, (int, float))
            else 0.0
        )

        signals["anchored"] = bool(
            decision.get("target") or decision.get("application")
        )

        if not isinstance(capability_id, str) or "." not in (
            capability_id
        ):
            return {
                "decisive": False,
                "signals": signals,
                "reasons": ("candidate is not a capability id",),
            }

        request = {
            token
            for token in re.findall(r"[a-z]{3,}", text.lower())
            if token not in cls._GROUNDING_STOPWORDS
        }

        descriptor = None
        try:
            from .capability_registry import CapabilityRegistry

            descriptor = CapabilityRegistry.get(capability_id)
        except Exception:
            descriptor = None

        if descriptor is not None:
            description_words = {
                token
                for token in re.findall(
                    r"[A-Za-z]{3,}", descriptor.description or ""
                )
                if token.lower() not in cls._GROUNDING_STOPWORDS
            }
            if description_words & request:
                signals["descriptor_overlap"] = True

        # The capability's OWN operation token, from its registered
        # id, matched against the request. This is not a hand-written
        # verb list: a new capability teaches the gate its own verb.
        operation = capability_id.split(".", 1)[1]
        operation_tokens = {
            token
            for token in re.split(r"[^a-z]+", operation.lower())
            # Short but real operation tokens matter: volume.up's
            # operation is "up", and a length filter long enough to
            # reject noise would also reject it. Function words are
            # excluded by the stopword set instead.
            if token and token not in cls._GROUNDING_STOPWORDS
        }
        # The request side needs the same short-token view, otherwise
        # "up" in "nudge the volume up a notch" is invisible and a
        # perfectly clear request looks unjustified.
        request_short = {
            token
            for token in re.findall(r"[a-z]{2,}", text.lower())
            if token not in cls._GROUNDING_STOPWORDS
        }
        if operation_tokens & request_short:
            signals["operation_named"] = True

        decisive = bool(
            signals["anchored"]
            or signals["operation_named"]
        )

        # descriptor_overlap is REPORTED but deliberately NOT part of
        # the decisive test. MEASURED and rejected as a criterion: the
        # fraction of a description covered by the request does not
        # separate decisive from ambiguous candidates. A case needing
        # a challenge scored 0.143 while a decisive case scored 0.111,
        # because "flatten this file into a printable layout" happens
        # to contain "file". Description vocabulary is shared across
        # capabilities and cannot carry this decision; treating it as
        # decisive reintroduces exactly the vocabulary proxy this
        # trigger is being replaced to remove.

        reasons: List[str] = []
        if not decisive:
            reasons.append(
                "deterministic candidate carries no per-request "
                "justification: no named target or application, and "
                "the request never names the operation it performs"
            )

        return {
            "decisive": decisive,
            "signals": signals,
            "reasons": tuple(reasons),
        }

    @classmethod
    def cross_domain_contradiction(
        cls,
        text: str,
        capability_id: Optional[str],
    ) -> bool:
        """
        True when the request names a DIFFERENT capability domain than
        the one the deterministic answer belongs to.

        Generic and domain-agnostic: it compares registry-derived
        domain vocabulary against the request, and it never prefers
        any particular domain, never counts terms, and never looks at
        benchmark wording.

        Conservative by construction, and measured to stay off the fast
        path: the matched domain's own vocabulary must be entirely
        absent from the request before a challenge is even
        considered. A clear match names its own domain —
        "open notepad" contains a token of the application domain,
        "lock my machine" one of workstation, "take a snapshot" one
        of screen — so all of those pay nothing.

        MEASURED: an earlier version ALSO required a competing
        domain to be literally named, which was too strict and
        missed real cases, because ordinary English rarely uses a
        capability-id token: a drawer is not spelled "folder" and an
        archive is not spelled "file". Absence of the matched
        domain is the sufficient signal; requiring a positive
        competing token discarded correct challenges.
        """
        if not isinstance(capability_id, str) or "." not in capability_id:
            return False
        domain = capability_id.split(".", 1)[0]
        vocabulary = cls.domain_tokens()
        if not vocabulary:
            return False

        request = {token for token in re.findall(r"[a-z]{3,}", text.lower())}
        if not request:
            return False

        own = vocabulary.get(domain) or frozenset()
        return not (own & request)

    @staticmethod
    def _shortlist_catalog() -> str:
        """
        Compact capability index: domain -> ids only.

        No descriptions, no boundary notes, no risk tags. This is
        stage one of a two-stage selection and exists because the
        full enriched catalog is too expensive to send on every
        request. MEASURED on the target host (CPU-only, 2 cores, no
        GPU, qwen2.5:7b): prefill runs at ~10 tokens/sec, so the
        5,480-token enriched prompt took 508 SECONDS per call and a
        40-item corpus would need ~5.7 hours. The same host does
        this index in roughly a tenth of that.
        """

        from .capability_registry import CapabilityRegistry

        by_domain: Dict[str, List[str]] = {}
        for capability in CapabilityRegistry.all():
            domain = capability.capability_id.split(".", 1)[0]
            by_domain.setdefault(domain, []).append(
                capability.capability_id
            )

        return "\n".join(
            f"{domain}: {', '.join(sorted(ids))}"
            for domain, ids in sorted(by_domain.items())
        )

    @staticmethod
    def _detail_catalog(capability_ids: Sequence[str]) -> str:
        """
        Full descriptors for a shortlist only.

        Boundary notes, risk and inputs are what actually decide
        the hard cases, so they are kept — but sent only for the
        handful of candidates still in contention.
        """

        from .capabilities import SELECTION_BOUNDARIES
        from .capability_registry import CapabilityRegistry

        lines: List[str] = []
        for capability_id in capability_ids:
            try:
                capability = CapabilityRegistry.get(capability_id)
            except Exception:
                continue
            parts = [capability.capability_id]
            if capability.risk_level != "low":
                parts.append(f"[{capability.risk_level}]")
            inputs = sorted(capability.supported_inputs)
            if inputs:
                parts.append(f"in=({','.join(inputs)})")
            parts.append(f"- {capability.description}")
            entry = " ".join(parts)
            boundary = SELECTION_BOUNDARIES.get(capability.capability_id)
            if boundary:
                entry += f"\n    BOUNDARY: {boundary}"
            lines.append(entry)
        return "\n".join(lines)

    def _shortlist(
        self,
        text: str,
        deadline: float,
        prior_turn: Optional[str] = None,
        probe: Optional[Dict[str, int]] = None,
    ) -> List[str]:
        """
        Stage one: which few capabilities could this possibly be?

        Returns real registry ids, best-guess first, or [] when the
        model declines (a legitimate answer meaning "not a computer
        request").

        ITEM 4: ``prior_turn`` adds the labelled prior-turn section.
        When None the prompt is byte-identical to before.

        Item 11A: ``probe`` is an out-parameter counting PROVIDER
        outcomes -- how many backend calls raised or returned junk, and
        how many actually replied. It exists because an empty list is
        ambiguous on its own: a dead provider and a healthy model
        correctly answering "this is not a computer request" both
        produce [], and only one of those is a failure. An empty
        shortlist must never trip the breaker on its own.
        """

        catalog = self._shortlist_catalog()
        prompt = (
            "Which Genesis OS capabilities could this request "
            "possibly mean?\n\n"
            f"CAPABILITY INDEX:\n{catalog}\n\n"
            "Pick AT MOST 5 ids that are genuinely plausible, best "
            "first. Copy ids EXACTLY. Choose by MEANING, not keyword "
            "overlap. If the request is not about controlling a "
            "computer, reply null.\n"
            "A WEB PAGE is browser.*, a document FILE is document.*, "
            "AUDIO is volume.* (display.* is screen brightness), and "
            "screenshot/screen capture is always screen.capture.\n\n"
            f'Reply ONLY with: {{"candidates": ["<id>", "<id>"]}}\n\n'
            f"{self._prior_turn_block(prior_turn)}"
            f"REQUEST: {text}\n\n"
            "JSON:"
        )

        for mode in self._backend_modes():
            if time.monotonic() >= deadline:
                return []
            try:
                raw = self._call_llm_with_timeout(
                    prompt, mode=mode
                )
            except Exception:
                _record_probe_error(probe)
                continue
            if not isinstance(raw, str):
                _record_probe_error(probe)
                continue
            _record_probe_reply(probe)
            parsed = (
                self._extract_json_preferring_valid_operation(raw)
            )
            if not isinstance(parsed, dict):
                continue
            candidates = parsed.get("candidates")
            if not isinstance(candidates, list):
                continue

            from .capability_registry import CapabilityRegistry

            resolved: List[str] = []
            for entry in candidates:
                if not isinstance(entry, str):
                    continue
                canonical = self._canonical_operation(
                    entry.strip().lower()
                )
                if canonical and canonical not in resolved:
                    resolved.append(canonical)
            if resolved:
                return resolved[:5]

        return []

    def _decide_from_shortlist(
        self,
        text: str,
        candidates: Sequence[str],
        deadline: float,
        prior_turn: Optional[str] = None,
        probe: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Stage two: pick exactly one from the shortlist, with full
        descriptors for the ambiguous cases.

        ITEM 4: ``prior_turn`` adds the labelled prior-turn section.
        When None the prompt is byte-identical to before.

        Item 11A: ``probe`` records PROVIDER outcomes for the breaker;
        see _shortlist for why None is not itself a failure.
        """

        catalog = self._detail_catalog(candidates)
        if not catalog:
            return None

        prompt = (
            "Choose the ONE Genesis OS capability that best matches "
            "the user's request.\n\n"
            f"CANDIDATES:\n{catalog}\n\n"
            "Choose by MEANING. Read the BOUNDARY notes: several "
            "families contain members with identical descriptions and "
            "the boundary states which member owns which meaning. "
            "CONVERT an existing file to another format is "
            "document.transform; AUTHOR new content in a format is "
            "document.create_<format>. Copy the chosen id EXACTLY.\n"
            "If none of these fit, reply null.\n"
            'Reply ONLY with: {"operation": "<exact id>", '
            '"target": "<what it acts on>", "parameters": {}}\n\n'
            f"{self._prior_turn_block(prior_turn)}"
            f"REQUEST: {text}\n\n"
            "JSON:"
        )

        for mode in self._backend_modes():
            if time.monotonic() >= deadline:
                return None
            try:
                raw = self._call_llm_with_timeout(
                    prompt, mode=mode
                )
            except Exception:
                _record_probe_error(probe)
                continue
            if not isinstance(raw, str):
                _record_probe_error(probe)
                continue
            _record_probe_reply(probe)
            parsed = (
                self._extract_json_preferring_valid_operation(raw)
            )
            if isinstance(parsed, dict) and isinstance(
                parsed.get("operation"), str
            ):
                return parsed
        return None

    def _resolve_two_stage(
        self,
        text: str,
        deadline: float,
        prior_turn: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Full two-stage selection, with the same safety validation
        and the same one-shot repair as the single-stage path.

        ITEM 4: ``prior_turn`` is threaded to both stages.

        ITEM 11A (R1): this is the DEFAULT path -- the single-stage
        prompt is only used when GENESIS_LLM_SINGLE_STAGE is set. It used
        to return here from ``resolve()`` WITHOUT ever touching the
        circuit breaker, so the breaker was checked (resolve() calls
        allow_request) but never updated. A provider that had been dead
        for hours was therefore retried on every single request, and the
        breaker could never open on the path that almost all traffic
        takes.

        The outcome is recorded in a ``finally`` so every exit is
        covered, including the many early returns in the body and any
        exception. Recording is driven by what the PROVIDER did, not by
        whether the request succeeded: a healthy model that correctly
        answers "this is not a computer request" records SUCCESS, and
        only a round where nothing replied at all records FAILURE.
        """

        probe: Dict[str, int] = {}
        try:
            return self._resolve_two_stage_body(
                text, deadline,
                prior_turn=prior_turn,
                probe=probe,
            )
        finally:
            self._record_two_stage_outcome(probe)

    def _record_two_stage_outcome(
        self,
        probe: Dict[str, int],
    ) -> None:
        """Feed the two-stage result into the SAME breaker the
        single-stage path uses -- same object, same thresholds.

        Item 11A. Precedence matters: if any backend call replied, the
        provider is reachable and that is a success for breaker purposes,
        even when the reply was a well-formed decline. Only a round in
        which NOTHING replied counts against the circuit.
        """

        if probe.get("replies", 0) > 0:
            self._circuit_breaker.record_success()
        elif probe.get("errors", 0) > 0:
            self._circuit_breaker.record_failure()

    def _resolve_two_stage_body(
        self,
        text: str,
        deadline: float,
        prior_turn: Optional[str] = None,
        probe: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:

        candidates = self._shortlist(
            text, deadline,
            prior_turn=prior_turn,
            probe=probe,
        )
        if not candidates:
            return None

        # A single candidate needs no second round trip.
        if len(candidates) == 1:
            parsed = {"operation": candidates[0], "parameters": {}}
        else:
            parsed = self._decide_from_shortlist(
                text, candidates, deadline,
                prior_turn=prior_turn,
                probe=probe,
            )
            if parsed is None:
                # Second stage declined or timed out. The
                # shortlist is still real semantic evidence, so
                # fall back to its top candidate rather than
                # discarding a correct understanding.
                parsed = {
                    "operation": candidates[0],
                    "parameters": {},
                }

        candidate = self._validated_candidate(text, parsed)
        if candidate is not None:
            return candidate

        proposed = parsed.get("operation")
        if not isinstance(proposed, str) or not proposed.strip():
            return None
        if self._canonical_operation(
            proposed.strip().lower()
        ) is not None:
            return None

        repaired = self._repair_invalid_operation(
            text=text,
            proposed=proposed.strip(),
            catalog=self._capability_catalog(),
            deadline=deadline,
        )
        if repaired is None:
            return None
        return self._validated_candidate(text, repaired)

    def resolve(
        self,
        text: str,
        prior_turn: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt to understand `text` as one OS capability.

        Returns a candidate workflow decision (confidence-capped,
        source-tagged) or None when no safe mapping exists.

        ITEM 4: ``prior_turn`` is the optional context channel. When
        None, every prompt built here is byte-identical to before.
        """

        if self.ai_engine is None:
            return None

        # --- Circuit breaker: skip if LLM is in failure cooldown ---
        if not self._circuit_breaker.allow_request():
            return None

        catalog = self._capability_catalog()

        if not catalog:
            return None

        prompt = self._build_prompt(
            text, catalog, prior_turn=prior_turn
        )

        # -----------------------------------------------------
        # BACKEND STRATEGY
        #
        # Order is chosen from MEASURED behaviour on real calls
        # with the enriched catalog (2026-09-26), not from a
        # general belief that "cloud is smarter".
        #
        #   mode=cloud  min 0.78s  max 26.47s  mean 9.86s
        #   mode=local  min 2.73s  max  5.98s  mean 3.83s
        #   mode=auto   min 0.89s  max  3.92s  mean 2.89s
        #
        # Latency alone favoured "auto" (it is fastest because it
        # delegates provider selection), and an earlier iteration
        # used that order. Correctness then contradicted it: on the
        # 10 hardest benchmark phrases, local returned a VALID
        # registry id every time it was consulted, while the
        # auto/cloud path twice invented ids that do not exist
        # ("file.create_intel", "file.save_as") and otherwise
        # returned HTTP 429 rate-limit errors. An invented id
        # wastes the whole round trip, so id-validity dominates
        # latency here. local therefore goes first; cloud and auto
        # remain as fallbacks so a missing or weak local model
        # cannot become the only opinion.
        #
        # Each call is wrapped in a ThreadPoolExecutor to bound
        # how long a slow provider can stall the caller.
        # -----------------------------------------------------

        parsed = None
        last_error = None

        deadline = time.monotonic() + self._RESOLVE_TOTAL_BUDGET

        # Two-stage selection is the default because the single-stage
        # prompt is unaffordable on a CPU-only host: MEASURED with
        # qwen2.5:7b on 2 cores at ~10 tok/s, the 5,480-token
        # enriched catalog took 508s per call. Stage one sends an
        # id-only index and stage two sends full descriptors for the
        # handful still in contention, which keeps the boundary
        # notes (they decide the hard cases) at a fraction of the
        # tokens. GENESIS_LLM_SINGLE_STAGE=1 restores the old path
        # for A/B measurement.
        if os.environ.get(
            "GENESIS_LLM_SINGLE_STAGE"
        ) not in ("1", "true", "yes"):
            return self._resolve_two_stage(
                text, deadline, prior_turn=prior_turn
            )

        for mode in self._backend_modes():
            if time.monotonic() >= deadline:
                break
            try:
                raw = self._call_llm_with_timeout(
                    prompt, mode=mode
                )
            except Exception as exc:
                last_error = exc
                continue

            if not isinstance(raw, str):
                continue

            parsed = (
                self._extract_json_preferring_valid_operation(raw)
            )

            if parsed is not None:
                break

        if parsed is None:
            if last_error is not None:
                self._circuit_breaker.record_failure()
            return None

        self._circuit_breaker.record_success()

        candidate = self._validated_candidate(text, parsed)

        if candidate is not None:
            return candidate

        # -----------------------------------------------------
        # SEMANTIC REPAIR — ONE SHOT
        # -----------------------------------------------------
        # The most common real failure is a model that understood
        # the request but named a capability that does not exist
        # ("file.create_intel", "file.save_as", "screen.take").
        # MEASURED 2026-09-26: on 3 of 10 hard phrases the model
        # invented an id, and the whole answer was then discarded
        # even though the intent was obvious and a valid id was
        # available. Rather than discard a correct understanding
        # over a spelling slip, feed the bad id back with the
        # genuinely-similar real ids and let the model correct
        # itself once.
        #
        # This is deliberately backend-agnostic. Measured quality
        # differed per provider (local Ollama returned valid ids
        # where Groq invented them, and Groq was simultaneously
        # returning HTTP 429), so betting on one provider would be
        # fragile. Repairing the model's mistake works regardless
        # of which provider answered.
        # -----------------------------------------------------

        proposed = parsed.get("operation") if isinstance(parsed, dict) else None
        if not isinstance(proposed, str) or not proposed.strip():
            return None

        if self._canonical_operation(proposed.strip().lower()) is not None:
            # The id was valid; the candidate was rejected for a
            # different, legitimate reason (safety policy, missing
            # parameters). Do not argue with that.
            return None

        repaired = self._repair_invalid_operation(
            text=text,
            proposed=proposed.strip(),
            catalog=catalog,
            deadline=deadline,
        )

        if repaired is None:
            return None

        return self._validated_candidate(text, repaired)

    def _repair_invalid_operation(
        self,
        *,
        text: str,
        proposed: str,
        catalog: str,
        deadline: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Ask the model to re-answer using a real capability id.

        Returns the repaired parsed answer, or None when the model
        declines (which is a legitimate outcome: the request may
        genuinely map to no registered capability).
        """

        from .capability_registry import CapabilityRegistry

        candidates = self._similar_capability_ids(proposed)

        nearby = (
            "\n".join(f"  {cid}" for cid in candidates)
            if candidates
            else "  (no similar id exists)"
        )

        prompt = (
            "You previously answered a capability-selection "
            "question with an operation id that does not exist in "
            "the Genesis capability registry.\n\n"
            f"USER REQUEST: \"{text}\"\n"
            f"YOUR INVALID ANSWER: {proposed}\n\n"
            "Real capability ids that are similar to your answer:\n"
            f"{nearby}\n\n"
            "The full registry is below. Choose the ONE id whose "
            "description matches what the user actually wants done, "
            "copying it EXACTLY.\n\n"
            f"{catalog}\n\n"
            "If no listed capability matches, reply null.\n"
            'Reply with ONLY: {"operation": "<exact id>", '
            '"target": "<what it acts on>", "parameters": {}}\n\n'
            "JSON:"
        )

        for mode in (None, "local", "cloud"):
            if time.monotonic() >= deadline:
                return None
            try:
                raw = self._call_llm_with_timeout(
                    prompt, mode=mode
                )
            except Exception:
                continue

            if not isinstance(raw, str):
                continue

            parsed = (
                self._extract_json_preferring_valid_operation(raw)
            )

            if isinstance(parsed, dict):
                operation = parsed.get("operation")
                if isinstance(operation, str) and (
                    self._canonical_operation(
                        operation.strip().lower()
                    )
                    is not None
                ):
                    return parsed

        return None

    @staticmethod
    def _similar_capability_ids(proposed: str) -> List[str]:
        """
        Real capability ids closest to a proposed (invalid) id.

        Ranked by shared token overlap plus string similarity, so
        the repair prompt shows the model the realistic options
        instead of the whole registry a second time.
        """

        import difflib

        from .capability_registry import CapabilityRegistry

        proposed_key = proposed.strip().lower()
        proposed_tokens = {
            t for t in proposed_key.replace(".", " ").split() if t
        }

        scored = []
        for capability_id in CapabilityRegistry.operations():
            key = capability_id.lower()
            tokens = {t for t in key.replace(".", " ").split() if t}
            overlap = len(proposed_tokens & tokens)
            ratio = difflib.SequenceMatcher(
                None, proposed_key, key
            ).ratio()
            scored.append((overlap, ratio, capability_id))

        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [cid for _, _, cid in scored[:8]]

    # Deterministic, bounded generation for capability selection.
    #
    # MEASURED 2026-09-27: with no sampling controls the
    # OpenAI-compatible endpoint defaulted to temperature 1.0, and
    # the same request returned DIFFERENT capabilities on repeated
    # calls in one session — "what is playing right now" resolved to
    # media.play_pause on one call and gui.read_visible_text on the
    # next. A control plane must be deterministic: the same request
    # has to map to the same capability, or the confirmation gate
    # and the audit trail mean nothing.
    #
    # The output bound matters too. With no max_tokens the model
    # occasionally kept generating until one request had run for
    # 10,859 seconds, and on an 11.9 GB host the orphaned workers of
    # several such calls exhausted RAM. Every prompt in this module
    # asks for one short JSON object, so a small cap is generous.
    _SELECTION_TEMPERATURE = 0.0
    _SELECTION_MAX_TOKENS = 256

    @classmethod
    def _selection_generation_kwargs(cls) -> Dict[str, Any]:
        return {
            "temperature": cls._SELECTION_TEMPERATURE,
            "max_tokens": cls._SELECTION_MAX_TOKENS,
        }

    def _call_llm_with_timeout(
        self,
        prompt: str,
        mode: Optional[str] = None
    ) -> str:
        """
        Call the AI engine with a hard timeout.

        Raises FuturesTimeoutError if the call exceeds
        _LLM_CALL_TIMEOUT, and propagates any other exception.
        """

        # The per-call timeout is genuinely enforced: on timeout the
        # worker is abandoned rather than joined, so a provider that
        # takes 40s cannot stall the caller for 40s. Abandoned
        # workers are bounded by _MAX_INFLIGHT_CALLS, because
        # unjoined workers that pile up saturate the provider and
        # cause the cascade documented on that constant. Both naive
        # variants were measured and both were worse — joining
        # defeats the timeout (observed 51.9s against an 8s budget)
        # and unbounded abandonment collapses accuracy (observed
        # 7/10 -> 2/10).
        if not self._acquire_inflight_slot():
            raise FuturesTimeoutError(
                "provider call budget exhausted "
                f"({self._inflight_cap()} calls already live)"
            )

        released = False

        def _release():
            nonlocal released
            if not released:
                released = True
                self._release_inflight_slot()

        def _do_call():
            try:
                if mode is None:
                    return self.ai_engine.generate_response(
                        prompt,
                        generation_kwargs=(
                            self._selection_generation_kwargs()
                        ),
                    )
                return self.ai_engine.generate_response(
                    prompt,
                    mode=mode,
                    generation_kwargs=(
                        self._selection_generation_kwargs()
                    ),
                )
            finally:
                _release()

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_do_call)
            return future.result(timeout=self._LLM_CALL_TIMEOUT)
        except FuturesTimeoutError:
            # The worker is abandoned but still holds its slot, so
            # start a bounded watchdog: if it has not released by
            # _INFLIGHT_HOLD_SECONDS the slot is force-released.
            # Without this, a cap of 1 turns one slow provider call
            # into a permanent loss of every following request.
            self._arm_inflight_watchdog()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)
            _release()
            raise
        else:
            executor.shutdown(wait=True)
            _release()

    # =========================================================
    # VALIDATION
    # =========================================================

    def _validated_candidate(
        self,
        original_text: str,
        parsed: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:

        from .capability_registry import CapabilityRegistry
        from .execution_safety import ExecutionSafety

        operation = parsed.get("operation")

        if not isinstance(operation, str) or not operation.strip():
            return None

        operation = self._canonical_operation(
            operation.strip().lower()
        )

        if operation is None:
            return None

        # -----------------------------------------------------
        # SAFETY FIRST: unknown / disabled / denied -> discard
        # -----------------------------------------------------

        from .capability_registry import CapabilityRegistry

        if not CapabilityRegistry.exists(operation):
            return None

        decision_check = ExecutionSafety.check(operation)

        if not decision_check.allowed:
            return None

        target = parsed.get("target")
        if not isinstance(target, str) or not target.strip():
            target = operation.split(".", 1)[0]

        raw_parameters = parsed.get("parameters")

        parameters = (
            dict(raw_parameters)
            if isinstance(raw_parameters, dict)
            else {}
        )

        # Sanitize parameter values into plain JSON types.
        clean_parameters = {}
        for key, value in parameters.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean_parameters[str(key)] = value

        # Small models name numeric inputs inconsistently
        # (value/level/amount/percentage). Normalize onto the
        # canonical parameter names used by dispatch.
        percent_aliases = ("percent", "value", "level", "amount", "percentage", "brightness")

        if operation in (
            "volume.set",
            "display.brightness_set",
        ):
            for alias in percent_aliases:
                if alias in clean_parameters:
                    try:
                        clean_parameters["percent"] = int(
                            float(str(clean_parameters[alias]).strip().rstrip("%"))
                        )
                    except (TypeError, ValueError):
                        pass
                    break

        return {
            "level": 3,
            "mode": "os",
            "task": original_text,
            "agent": None,
            "agents": [],
            "intent": operation,
            "operation": operation,
            "application": None,
            "target": target.strip(),
            "parameters": clean_parameters,
            # Honest confidence: this came from an AI proposal,
            # NOT from deterministic understanding. It is always
            # below the executor's automatic threshold, forcing
            # the explicit confirmation flow.
            "confidence": self.PROPOSAL_CONFIDENCE_CAP,
            "reason": (
                "An AI-resolved interpretation of your request; "
                "confirmation required."
            ),
            "engine_version": self.VERSION,
            "source": "LLMIntentResolver",
        }

    # =========================================================
    # INTERNALS
    # =========================================================

    @staticmethod
    def _build_prompt(
        text: str,
        catalog: str,
        prior_turn: Optional[str] = None,
    ) -> str:
        # ITEM 4: the optional prior-turn section. Empty when absent,
        # so the prompt below is byte-identical to the pre-Item-4 one.
        # This is the single-stage path (GENESIS_LLM_SINGLE_STAGE=1);
        # the default two-stage path threads the same section through
        # _shortlist and _decide_from_shortlist.
        context = LLMIntentResolver._prior_turn_block(prior_turn)
        context_rule = (
            "- The REQUEST may refer back to the PREVIOUS TURN with a "
            "word like \"that\", \"it\" or \"this one\". Resolve the "
            "reference against the PREVIOUS TURN and choose the "
            "capability the referent implies.\n"
            if context else ""
        )
        return f"""You map a user's computer-control request onto ONE Genesis OS capability.

CAPABILITIES (grouped by category; id [risk] inputs - description):
{catalog}

HOW TO CHOOSE:
- Choose by MEANING, not keyword overlap. Work out what the user wants DONE to their computer, then find the capability whose description and BOUNDARY note say exactly that.
- Read the BOUNDARY notes. Several families contain members with identical descriptions; the boundary note says which member owns which meaning. Ignoring them causes arbitrary choices.
- DOMAIN matters: a WEB PAGE is browser.*, a document FILE is document.*. AUDIO is volume.*, never display.* (display is screen brightness).
- CONVERT an existing file to another format = document.transform. AUTHOR new content in a format = document.create_<format>.
- The only id for any screenshot / screen capture is screen.capture. To close an application use application.close; window.* only minimises, restores or shows the desktop.

EXAMPLES:
"grab what's on my screen and save it" -> {{"operation": "screen.capture", "target": "screen", "parameters": {{}}}}
"I can barely see this, fix it" -> {{"operation": "display.brightness_set", "target": "brightness", "parameters": {{"direction": "up"}}}}
"play the next song" -> {{"operation": "media.next", "target": "media", "parameters": {{}}}}
"navigate to example.com" -> {{"operation": "browser.open_url", "target": "url", "parameters": {{}}}}
"scan for nearby wifi signals" -> {{"operation": "network.list_wifi", "target": "network", "parameters": {{}}}}
"lock this machine" -> {{"operation": "workstation.lock", "target": "workstation", "parameters": {{}}}}
"find and replace all instances of draft in this report" -> {{"operation": "document.edit", "target": "document", "parameters": {{"find_text": "draft", "replace_text": ""}}}}
"copy that paragraph to my clipboard" -> {{"operation": "clipboard.copy", "target": "clipboard", "parameters": {{"text": "the text to copy"}}}}
"paste what I copied earlier" -> {{"operation": "clipboard.paste", "target": "clipboard", "parameters": {{}}}}

NOT computer-control requests - reply null:
"what's the weather in paris" -> null
"hii now i make you able to control my computer" -> null
"that genuinely cheered me up" -> null
"she set the table before we arrived" -> null
"i think we should set up a meeting" -> null

RULES:
- The "operation" MUST be copied EXACTLY from a listed id, character for character. Never invent, guess, abbreviate or pluralise an id (there is no screen.take, no window.close, no doc.read, no file.save_as). If no listed id matches the meaning, reply null.
- Choose exactly ONE operation, or reply null.
- Reply with ONLY a JSON object on the first line. No explanation, no second JSON object, no markdown fence.
- Format: {{"operation": "<exact id>", "target": "<what it acts on>", "parameters": {{}}}}
- Only use parameter names listed in that capability's in=(...) list. Never invent a parameter. Numbers must be JSON numbers.
- If the user is chatting, asking an opinion, or describing a state rather than requesting a computer action, reply null.
{context_rule}
{context}REQUEST: "{text}"

JSON:"""

    @staticmethod
    def _canonical_operation(proposed: str) -> Optional[str]:
        """
        Map a model-proposed operation id onto the registered
        catalog deterministically.

        Exact match first; then a UNIQUE suffix match so that
        "brightness_set" resolves to "display.brightness_set"
        while ambiguous proposals are discarded, never guessed.
        """

        from .capability_registry import CapabilityRegistry

        proposed = proposed.strip().lower().replace(" ", "_")

        if CapabilityRegistry.exists(proposed):
            return proposed

        # Item 12E (R7): the grouping is now explicit.
        #
        # This read, with no parentheses around the boolean part:
        #
        #     if "." in capability_id
        #     and capability_id.split(".", 1)[1] == proposed
        #     or capability_id.replace(".", "_") == proposed
        #
        # Python binds `and` tighter than `or`, so it was always
        # evaluating as
        #
        #     ("." in capability_id and suffix == proposed)
        #         or (flattened == proposed)
        #
        # and that is what it should be, but nothing said so. The
        # parentheses that ARE on those lines belong to .split(".", 1)
        # and .replace(".", "_") -- method-call arguments -- so a reader
        # scanning for grouping would find none. The other candidate
        # reading, `"." in capability_id and (suffix == proposed or
        # flattened == proposed)`, reads plausibly enough to be
        # mistaken for the intended one.
        #
        # CHECKED BEFORE PARENTHESISING, because the point of the fix is
        # to state the truth rather than pick a tidier story. Every one
        # of the 143 registered operations contains a dot, and probing
        # all 399 distinct proposals reachable from the registry (every
        # id, every dotted suffix, every flattened form, plus junk)
        # produced ZERO cases where the two groupings disagree. So the
        # explicit grouping below documents existing behaviour exactly;
        # it changes nothing.
        suffix_matches = [
            capability_id
            for capability_id in CapabilityRegistry.operations()
            if (
                # the suffix after the FIRST dot, e.g. brightness_set
                "." in capability_id
                and capability_id.split(".", 1)[1] == proposed
            )
            # OR the whole id flattened, e.g. file_save_as
            or capability_id.replace(".", "_") == proposed
        ]

        if len(suffix_matches) == 1:
            return suffix_matches[0]

        return None

    @staticmethod
    def _capability_catalog() -> str:
        """
        Enriched, category-grouped catalog of executable
        capabilities.

        Includes ALL registered capabilities - even dangerous ones.
        Safety is enforced by the prompt rule ("never invent
        operations"), the executor's confirmation gate, and
        ExecutionSafety checks - not by hiding capabilities from
        the model.  Excluding dangerous ops from the catalog
        creates a structural gap where the LLM cannot map valid
        user requests (e.g. "get rid of this file") to their
        correct operation.

        Phase 3: each entry additionally carries its risk tier and,
        where a capability family is genuinely ambiguous, a
        SELECTION_BOUNDARY note. Several families contain
        near-duplicate members whose descriptions are identical
        (document.summarize / summarize_intel, spreadsheet.read /
        read_intel, browser.find / find_text); without the
        boundary notes those pairs are undecidable and selection
        degenerates into a coin flip. Grouping by category also
        lets the model narrow by domain before reading detail.
        """

        from .capabilities import SELECTION_BOUNDARIES
        from .capability_registry import CapabilityRegistry

        grouped: Dict[str, List[str]] = {}

        for capability in sorted(
            CapabilityRegistry.all(),
            key=lambda c: c.capability_id,
        ):
            category = str(
                getattr(
                    capability.category,
                    "value",
                    capability.category,
                )
            )
            boundary = SELECTION_BOUNDARIES.get(
                capability.capability_id
            )
            parts = [f"  {capability.capability_id}"]
            if capability.risk_level != "low":
                parts.append(f"[{capability.risk_level}]")
            inputs = sorted(capability.supported_inputs)
            if inputs:
                parts.append(f"in=({','.join(inputs)})")
            parts.append(f"- {capability.description}")
            entry = " ".join(parts)
            if boundary:
                entry += f"\n      BOUNDARY: {boundary}"
            grouped.setdefault(category, []).append(entry)

        blocks = []
        for category in sorted(grouped):
            blocks.append(
                f"[{category.upper()}]\n"
                + "\n".join(grouped[category])
            )

        return "\n".join(blocks)

    @staticmethod
    def _extract_json(raw: str) -> Optional[Any]:
        """
        Extract the first JSON object from a noisy model answer.
        """

        raw = raw.strip()

        # Direct parse.
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass

        # Strip markdown fences.
        fenced = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            raw,
            re.DOTALL,
        )
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # First balanced braces block.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    @staticmethod
    def _iter_json_objects(text: str) -> List[Any]:
        """
        Yield every top-level JSON object embedded in `text`.

        A non-greedy ``\\{.*?\\}`` regex is NOT sufficient: it stops
        at the first closing brace, which for a payload like
        ``{"operation": "x", "parameters": {}}`` is the brace of
        the nested empty object, yielding malformed JSON that then
        fails to parse. This walks the string tracking brace depth
        (and string literals, so a brace inside a quoted value does
        not confuse the depth) and returns each balanced object.
        """

        objects: List[Any] = []
        index = 0
        length = len(text)

        while index < length:
            if text[index] != "{":
                index += 1
                continue

            depth = 0
            in_string = False
            escaped = False
            cursor = index

            while cursor < length:
                char = text[cursor]

                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                elif char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        chunk = text[index:cursor + 1]
                        try:
                            objects.append(json.loads(chunk))
                        except (json.JSONDecodeError, ValueError):
                            pass
                        index = cursor
                        break

                cursor += 1
            else:
                # Unbalanced: no complete object from here.
                break

            index += 1

        return objects

    @staticmethod
    def _extract_json_preferring_valid_operation(
        raw: str,
    ) -> Optional[Any]:
        """
        Extract a JSON answer, preferring one whose ``operation``
        is a real registered capability.

        Models sometimes emit several JSON objects when unsure
        (a first guess, then a second, then prose). Taking the
        first object blindly means an invented id such as
        ``screen.take`` discards the whole answer even when a
        later object names a valid capability. This walks every
        JSON object in the answer and returns the first whose
        operation canonicalises onto the registry, falling back to
        the first parseable object so the existing validation
        path still produces its usual "unknown operation"
        rejection.

        A literal ``null`` answer is preserved as None: "this is
        not a computer request" must never be overridden by a
        stray object later in the text.
        """

        if not isinstance(raw, str):
            return None

        text = raw.strip()

        # An explicit null answer is authoritative.
        if text.lower().startswith("null"):
            return None

        candidates: List[Any] = []

        try:
            candidates.append(json.loads(text))
        except (json.JSONDecodeError, ValueError):
            pass

        for candidate in LLMIntentResolver._iter_json_objects(text):
            if candidate not in candidates:
                candidates.append(candidate)

        if not candidates:
            return LLMIntentResolver._extract_json(raw)

        first_mapping = None

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if first_mapping is None:
                first_mapping = candidate
            operation = candidate.get("operation")
            if not isinstance(operation, str) or not operation.strip():
                continue
            if LLMIntentResolver._canonical_operation(
                operation.strip().lower()
            ) is not None:
                return candidate

        return first_mapping
