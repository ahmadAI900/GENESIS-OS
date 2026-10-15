"""
Debug: check what the LLM intent resolver actually returns.
"""
import sys
import time
sys.path.insert(0, '.')

from ai.providers import GroqProvider
from genesis_os.llm_intent_resolver import LLMIntentResolver
from ai.ai_engine import AIEngine
from agents.workflow_decision import WorkflowDecisionEngine

groq = GroqProvider(api_key="REDACTED_GROQ_KEY")
ai = AIEngine(providers=[groq])
wde = WorkflowDecisionEngine()
intent = LLMIntentResolver(ai_engine=ai, decision_engine=wde)

# Test one phrase and see the raw response
phrase = "condense this into a brief overview"
print("Phrase:", phrase)
print("Looks actionable:", LLMIntentResolver.looks_actionable(phrase))

# Manually build the prompt and call the LLM
catalog = intent._capability_catalog()
prompt = LLMIntentResolver._build_prompt(phrase, catalog)
print()
print("Prompt (last 500 chars):")
print(prompt[-500:])
print()

# Call the LLM directly
try:
    response = ai.generate_response("Reply with ONLY a JSON object. " + prompt, mode="cloud")
    print("Raw LLM response:")
    print(repr(response[:500]))
except Exception as e:
    print("LLM error:", e)

# Also try resolve
try:
    result = intent.resolve(phrase)
    print()
    print("resolve() result:", result)
except Exception as e:
    print("resolve() error:", e)
