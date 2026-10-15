from brain.brain import Brain
import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real cloud LLM call via Brain().process_request.
# --------------------------------------------------------------
pytestmark = pytest.mark.live
brain = Brain()
response = brain.process_request("what is my favorite programming language?")
print("GENESIS", response)
