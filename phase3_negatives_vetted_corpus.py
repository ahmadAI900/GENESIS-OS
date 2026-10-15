"""
Phase 3 Item 2 -- an adversarially-vetted NEGATIVE set.

WHY THIS EXISTS
---------------
`final4` measured 4/20 = 20.0% false positives against a <=5% bar, and
carried an explicit caveat: its 20 negatives were agent-drafted in one
pass, not adversarially vetted the way `final3`'s original 8 were. That
caveat was an ASSUMPTION. This module exists to test it.

RIGOR APPLIED, MATCHING THE `final3` NEGATIVES
----------------------------------------------
* Every item must be a request Genesis must DECLINE. Negatives carry no
  capability answer to leak, so agent-drafting is legitimate here, exactly
  as it was for every prior negative set in this phase.
* Every item is chosen to attack a KNOWN weak point, not to be easy.
  The five families below each target a specific measured failure mode.
* Every item is fragment-matched against prompts, boundary notes, few-shot
  examples, gate vocabulary, the deterministic regex layer and BOTH sealed
  corpora. Anything with a significant overlap must be rewritten. Enforced
  mechanically by `phase3_negatives_vetted_audit.py`, not by inspection.

THE FAMILIES
------------
`knowledge_action_adjacent`
    A knowledge or how-to question carrying an action verb. This is the
    measured `looks_actionable` weak spot: the request sounds procedural
    but asks for no change to the machine. A system that resolves one of
    these has confused "explain" with "do".

`smalltalk`
    Greetings, thanks, presence checks. Cheap individually; a batch of them
    is what separates a gate from a keyword match.

`narration_not_request`
    Past-tense description of something already done. Contains every
    capability's vocabulary and requests nothing.

`advice_not_action`
    Asking what someone should do, or for a recommendation. The verb is an
    action verb; the intent is counsel.

`unexecutable_ambiguity`
    Genuinely vague with nothing to act on. Must decline rather than invent
    a target.

`ambiguous_even_with_context`
    Carries a `prior` turn that does NOT resolve the reference. These exist
    to test the cost of Item 4's discriminativeness widening directly: with
    a prior present, the grounding denominator widens, so this family
    measures whether that widening let anything through that should not
    have been. Every one of them must still decline.

NOTE ON `prior`
---------------
Items carrying a `prior` are still NEGATIVES. They are deliberately NOT
context items: the context channel is given its chance and the answer must
still be "no action". `phase3_final4_score.classify` keys on `prior` and
would file these as context, so the remeasurement scorer
(`phase3_fp_remeasure.py`) classifies on the absence of `expect` instead,
and reports the two families separately so the widening cost is legible.
"""

from __future__ import annotations

from typing import Any, Dict, List

NEGATIVES_VETTED: List[Dict[str, Any]] = [
    # -----------------------------------------------------------
    # knowledge_action_adjacent -- action verbs, no machine action
    # -----------------------------------------------------------
    {
        "phrase": "how do I work out compound interest by hand",
        "category": "knowledge_action_adjacent",
        "source": "agent",
        "reason": "procedural maths question; no file, app or setting is "
                  "named and nothing is asked to change",
    },
    {
        "phrase": "explain how a hash table resolves collisions",
        "category": "knowledge_action_adjacent",
        "source": "agent",
        "reason": "'resolves' is a capability-shaped verb used purely "
                  "rhetorically about a data structure",
    },
    {
        "phrase": "what time zone does Lisbon observe in summer",
        "category": "knowledge_action_adjacent",
        "source": "agent",
        "reason": "asks for a fact; 'observe' must not read as a window "
                  "operation",
    },
    {
        "phrase": "tell me which sorting algorithm is fastest for large "
                  "random arrays",
        "category": "knowledge_action_adjacent",
        "source": "agent",
        "reason": "'sorting' is spreadsheet.sort vocabulary in a pure "
                  "knowledge question",
    },
    {
        "phrase": "walk me through converting a CSV into a spreadsheet "
                  "by hand",
        "category": "knowledge_action_adjacent",
        "source": "agent",
        "reason": "narrates a manual conversion; the user is not asking "
                  "Genesis to convert anything",
    },
    {
        "phrase": "who first described the Krebs cycle",
        "category": "knowledge_action_adjacent",
        "source": "agent",
        "reason": "the classic weak spot named in the 1b-era finding -- "
                  "an author query with no action verb at all",
    },
    {
        "phrase": "how would you normally rename a variable in a "
                  "codebase",
        "category": "knowledge_action_adjacent",
        "source": "agent",
        "reason": "'rename' is file.rename vocabulary; the question is "
                  "about convention, not about the user's disk",
    },

    # -----------------------------------------------------------
    # smalltalk
    # -----------------------------------------------------------
    {
        "phrase": "morning, hope you are having a decent day",
        "category": "smalltalk",
        "source": "agent",
        "reason": "pure greeting",
    },
    {
        "phrase": "thanks, that was genuinely helpful",
        "category": "smalltalk",
        "source": "agent",
        "reason": "acknowledgement only",
    },
    {
        "phrase": "are you still there",
        "category": "smalltalk",
        "source": "agent",
        "reason": "presence check",
    },
    {
        "phrase": "good evening to you",
        "category": "smalltalk",
        "source": "agent",
        "reason": "greeting; must not read as an application launch",
    },

    # -----------------------------------------------------------
    # narration_not_request -- capability vocabulary, no request
    # -----------------------------------------------------------
    {
        "phrase": "I already moved the quarterly folder across to the "
                  "archive drive yesterday",
        "category": "narration_not_request",
        "source": "agent",
        "reason": "reports a completed folder.move; past tense, nothing "
                  "requested",
    },
    {
        "phrase": "last night I copied the tax documents onto the external "
                  "drive",
        "category": "narration_not_request",
        "source": "agent",
        "reason": "reports a completed file.copy",
    },
    {
        "phrase": "the screenshot I took earlier ended up in my downloads "
                  "folder",
        "category": "narration_not_request",
        "source": "agent",
        "reason": "mentions screen.capture and a folder path without "
                  "asking for either",
    },

    # -----------------------------------------------------------
    # advice_not_request
    # -----------------------------------------------------------
    {
        "phrase": "should I keep the archive folder nested or flat",
        "category": "advice_not_request",
        "source": "agent",
        "reason": "requests a recommendation about folder structure",
    },
    {
        "phrase": "what would you do about a spreadsheet with a broken "
                  "formula",
        "category": "advice_not_request",
        "source": "agent",
        "reason": "asks for counsel about a spreadsheet, not a repair",
    },

    # -----------------------------------------------------------
    # unexecutable_ambiguity
    # -----------------------------------------------------------
    {
        "phrase": "do the needful with the rest of it",
        "category": "unexecutable_ambiguity",
        "source": "agent",
        "reason": "names no object and no operation",
    },
    {
        "phrase": "deal with the situation however you judge best",
        "category": "unexecutable_ambiguity",
        "source": "agent",
        "reason": "definite reference to an unspecified thing, with "
                  "nothing supplied and no prior",
    },
    {
        "phrase": "make things a bit nicer all round",
        "category": "unexecutable_ambiguity",
        "source": "agent",
        "reason": "no target, no operation, no measurable outcome",
    },

    # -----------------------------------------------------------
    # ambiguous_even_with_context -- prior supplied, still must fail
    # -----------------------------------------------------------
    {
        "phrase": "can you sort that out for me",
        "prior": "I have been thinking about the weather a lot this week.",
        "category": "ambiguous_even_with_context",
        "source": "agent",
        "reason": "the prior names no object at all, so it cannot resolve "
                  "'that'; tests whether Item 4's widened "
                  "discriminativeness lets a content-free referent through",
    },
    {
        "phrase": "put a copy of it somewhere sensible",
        "prior": "It has been a strange week for a number of reasons.",
        "category": "ambiguous_even_with_context",
        "source": "agent",
        "reason": "file.copy-shaped request with neither the referent nor "
                  "the destination established by the prior",
    },
    {
        "phrase": "close the other one",
        "prior": "There has been a good deal going on at the office lately.",
        "category": "ambiguous_even_with_context",
        "source": "agent",
        "reason": "an explicit reference to one of several open things, "
                  "where the prior does not establish which; must decline "
                  "rather than pick",
    },
    {
        "phrase": "take that out of the list",
        "prior": "The train was delayed again this morning.",
        "category": "ambiguous_even_with_context",
        "source": "agent",
        "reason": "the referent is never established and the prior is "
                  "topically unrelated",
    },
]


def all_negatives() -> List[Dict[str, Any]]:
    """Every vetted negative, in declaration order."""
    return list(NEGATIVES_VETTED)


def by_category() -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in NEGATIVES_VETTED:
        grouped.setdefault(item["category"], []).append(item)
    return grouped


def with_context() -> List[Dict[str, Any]]:
    """The subset carrying a prior turn -- all still negatives."""
    return [item for item in NEGATIVES_VETTED if item.get("prior")]


def without_context() -> List[Dict[str, Any]]:
    return [item for item in NEGATIVES_VETTED if not item.get("prior")]