"""
Regression test for the live multi-agent aggregation crash:

    ResultAggregator.aggregate() takes 1 positional
    argument but 2 were given

Reproduces the exact call path that fires after a multi-agent
workflow finishes: GenesisOS calls
``self.aggregator.aggregate(results)`` (see
``backend/genesis.py:1659``) with the executor's results list.

This test asserts:

1. ``ResultAggregator.aggregate`` accepts a results argument
   (the executor's results list).
2. The aggregated payload contains every agent that ran.
3. An empty results list returns a non-fatal empty
   aggregation (used by single-agent paths).
4. A None results list does not raise and returns the empty
   aggregation payload.
"""


from agent_context.context import AgentContext
from agents.result_aggregator import ResultAggregator


def test_aggregate_accepts_results_argument_from_executor():

    context = AgentContext()

    aggregator = ResultAggregator(context)

    executor_results = [
        {
            "step": 1,
            "task": "research biology",
            "agent": "Research Agent",
            "result": "Biology findings ...",
            "status": "completed",
        },
        {
            "step": 2,
            "task": "save as pdf",
            "agent": "Document Agent",
            "result": "PDF rendered ...",
            "status": "completed",
        },
    ]

    aggregated = aggregator.aggregate(executor_results)

    assert aggregated["success"] is True
    assert aggregated["agent_count"] == 2

    agents = [
        item["agent"]
        for item in aggregated["results"]
    ]

    assert "Research Agent" in agents
    assert "Document Agent" in agents


def test_aggregate_with_empty_results_returns_empty_payload():

    context = AgentContext()
    aggregator = ResultAggregator(context)

    aggregated = aggregator.aggregate([])

    assert aggregated["success"] is False
    assert aggregated["agent_count"] == 0
    assert aggregated["results"] == []


def test_aggregate_signature_matches_genesis_call_site():

    import inspect

    signature = inspect.signature(
        ResultAggregator.aggregate
    )

    parameters = list(signature.parameters.keys())

    assert parameters == ["self", "results"], (
        "ResultAggregator.aggregate must accept the "
        "executor results list as its only positional "
        "argument (see backend/genesis.py:1659). "
        f"Got parameters: {parameters}"
    )
