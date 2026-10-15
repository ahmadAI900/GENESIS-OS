"""Trace exactly why each of the 7 phrases is rejected."""
import sys, re
sys.path.insert(0, '.')
from genesis_os.llm_intent_resolver import LLMIntentResolver

SEVEN = [
    ("how do these two versions differ", "document.compare"),
    ("these two sheets don't match, compare them", "spreadsheet.compare"),
    ("what does this workbook contain", "spreadsheet.inspect"),
    ("where am I right now on the web", "browser.get_url"),
    ("how much room is left on my drive", "hardware.storage"),
    ("what are my system resources doing", "hardware.stats"),
    ("what processes are active", "process.list"),
]

ACTION_RE = LLMIntentResolver._ACTION_HINT_RE
POLITE_RE = LLMIntentResolver._POLITE_PREFIX_RE
INTERJ_RE = LLMIntentResolver._INTERJECTION_RE

QUESTION_WORDS = re.compile(
    r"^(what|how|why|when|where|which|who|"
    r"can|could|would|should|is|are|am|do|does|"
    r"did|have|has|will|shall|may|might)"
    r"('s|'t|'re|'ve|'ll|'m)?$",
    re.IGNORECASE,
)

for phrase, expected in SEVEN:
    print(f"\n{'='*70}")
    print(f"  PHRASE: \"{phrase}\"")
    print(f"  EXPECTED: {expected}")
    print(f"{'='*70}")

    # Step 1: command_core stripping
    core = LLMIntentResolver._command_core(phrase)
    print(f"  command_core: \"{core}\"")

    # Step 2: Check 1 - first word must fullmatch ACTION_HINT_RE
    if core is not None:
        first_match = re.match(r"^\W*([A-Za-z]+)", core)
        if first_match:
            first_word = first_match.group(1)
            matches = bool(ACTION_RE.fullmatch(first_word))
            print(f"  Check 1: first_word=\"{first_word}\" fullmatch={matches}")
            if matches:
                print(f"  -> PASS (Check 1)")
                continue
        else:
            print(f"  Check 1: no first word found")
    else:
        print(f"  Check 1: core is None")

    # Step 3: Check 2 - question word + action verb in first 6 words
    if core is not None:
        core_first = re.match(r"^\W*([A-Za-z']+)", core)
        if core_first:
            fw = core_first.group(1)
            is_qw = bool(QUESTION_WORDS.match(fw))
            print(f"  Check 2: first_word=\"{fw}\" is_question_word={is_qw}")

            if is_qw:
                core_words = core.split()
                head = " ".join(core_words[:6])
                print(f"  Check 2: head_6=\"{head}\"")

                action_in_head = ACTION_RE.search(head)
                print(f"  Check 2: action_verb_in_head={bool(action_in_head)}")
                if action_in_head:
                    print(f"  Check 2: matched verb=\"{action_in_head.group()}\"")
                    print(f"  -> PASS (Check 2)")
                    continue
                else:
                    # Show which words are NOT in the regex
                    print(f"  Check 2: REJECTED - no action verb in first 6 words")
                    print(f"    Words checked: {core_words[:6]}")
                    for w in core_words[:6]:
                        in_regex = bool(ACTION_RE.fullmatch(w))
                        print(f"      \"{w}\" in regex: {in_regex}")
            else:
                print(f"  Check 2: REJECTED - \"{fw}\" is not a question word")
        else:
            print(f"  Check 2: no core_first match")
    else:
        print(f"  Check 2: core is None")

    print(f"  -> FINAL: REJECTED")

print(f"\n{'='*70}")
print("  ANALYSIS")
print(f"{'='*70}")
print()
print("  The gate rejects these because:")
print("  Check 1: first word after stripping must be an action verb (fullmatch)")
print("  Check 2: if first word IS a question word, an action verb must appear")
print("           within the first 6 words of the core")
print()
print("  For state-verb questions ('differ', 'contain', 'active', 'doing'),")
print("  the action concept is expressed as a STATE, not an ACTION VERB.")
print("  The gate has no mechanism to map state-verbs to their action equivalents.")
