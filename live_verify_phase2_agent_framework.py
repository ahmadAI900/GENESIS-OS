"""
Phase 2 Agent Framework Adapter - LIVE VERIFICATION
====================================================

This script is the actual acceptance gate for Phase 2 of the UCCL
roadmap.  Per ``phase2_agent_framework_adapter.md``:

    write a small standalone script that constructs a real Agent
    Framework agent/client (using whichever backend is configured
    in this project's ``.env`` - reuse existing ``AIEngine``
    credentials/config rather than hardcoding new ones) with these
    five tools registered, sends it a real natural-language
    request that should trigger ONE of the five tools (e.g.
    "open notepad" or "read this file: <path>"), and shows the
    actual console output of:

        the model's tool call
        the adapter routing it to the real executor
        the real verified result coming back.

Run with:

    cd C:\\Users\\Muhammad\\Desktop\\gemini_cli\\backend
    python live_verify_phase2_agent_framework.py

The script reuses ``AIEngine`` to load the first available compatible
provider configuration (OpenRouter, Groq, or local Ollama) from
``backend/.env``. It does NOT hardcode new credentials. It builds a
real ``OpenAIChatCompletionClient`` against that provider's
OpenAI-compatible base URL and registers the five Phase 2
capabilities through ``AgentFrameworkAdapter`` so the model can call
them.

The script sends one well-scoped natural-language request per
run ("open notepad").  The Agent Framework function-invocation
loop dispatches the model's tool call through
``AgentFrameworkAdapter.execute_capability``, which routes through
the real ``ActionExecutor.execute`` (the same code path the
workflow engine uses) and back.  The console output below is the
real round-trip.

A configured compatible provider is used in the order exposed by
AIEngine (OpenRouter, Groq, then local Ollama). No new credentials
are introduced; the selected provider and model are printed in the
transcript.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Make sure the backend package is importable when this script
# is run from outside the package root.
_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv

# Force-load the project's existing .env so AIEngine and the
# OpenAI client pick up the same OPENROUTER_* values that the
# rest of Genesis already uses.
load_dotenv(_BACKEND_ROOT / ".env", override=False)


def hr(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def section(title: str) -> None:
    print()
    print("--- " + title + " ---")


# =========================================================
# 1. LOAD EXISTING AIENGINE CONFIG (no new credentials)
# =========================================================


def load_credentials() -> Dict[str, Any]:
    """
    Reuse the AIEngine-configured OpenRouter key, base URL, and
    model.  We deliberately do not hardcode new credentials; we
    call ``AIEngine`` so the live verification uses the exact
    same configuration the rest of Genesis already uses.
    """

    from ai.ai_engine import AIEngine

    engine = AIEngine()
    if engine.cloud_available:
        return {
            "api_key": engine.api_key,
            "base_url": engine.api_base_url,
            "model": engine.cloud_model,
            "ai_mode": engine.mode,
            "source": "openrouter",
        }
    groq = engine._get_provider("Groq")
    if groq is not None and groq.is_available:
        return {
            "api_key": groq._api_key,
            "base_url": groq._base_url,
            "model": groq.model_id,
            "ai_mode": engine.mode,
            "source": "groq",
        }
    if engine.local_available:
        return {
            "api_key": engine.ollama_api_key,
            "base_url": engine.ollama_base_url,
            "model": engine.local_model,
            "ai_mode": engine.mode,
            "source": "ollama",
        }
    raise RuntimeError(
        "No compatible AI backend is available - check the "
        "AIEngine cloud or local Ollama configuration."
    )


# =========================================================
# 2. BUILD THE AGENT FRAMEWORK AGENT
# =========================================================


async def build_agent_and_tools():
    """
    Construct a real Microsoft Agent Framework ``Agent`` with
    the five Phase 2 capabilities registered as Agent Framework
    function tools, using an ``OpenAIChatCompletionClient``
    configured with AIEngine's OpenRouter credentials.
    """

    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatCompletionClient
    from openai import AsyncOpenAI

    from genesis_os.agent_framework_adapter import (
        AgentFrameworkAdapter,
        POC_CAPABILITIES,
        build_default_adapter,
    )

    creds = load_credentials()
    api_key = creds["api_key"]
    base_url = creds["base_url"]
    model = creds["model"]

    section("AIEngine credentials (reused, NOT new)")
    print("source     =", creds["source"])
    print("model      =", model)
    print("base_url   =", base_url)
    print("api_key    =", (api_key[:8] + "...") if api_key else "(missing)")

    # OpenAIChatCompletionClient requires an AsyncOpenAI client.
    # We build it from the same key/base_url AIEngine uses so the
    # adapter agent shares the same credentials as the rest of
    # Genesis.
    async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    chat_client = OpenAIChatCompletionClient(
        model=model,
        async_client=async_client,
    )

    # Build the adapter around the REAL ActionExecutor.
    # ``build_default_adapter()`` constructs OSManager + ActionExecutor
    # exactly as ``genesis.py`` does, so the live verification goes
    # through the same pipeline.
    adapter = build_default_adapter()

    tools = adapter.build_tools()

    section("Phase 2 capabilities registered as Agent Framework tools")
    for t in tools:
        print(
            f"  - {t.name:24s}  "
            f"description: {t.description[:60]}..."
        )

    instructions = (
        "You are a Genesis desktop assistant. "
        "When the user asks you to open a desktop application, "
        "use the appropriate tool from the available set. "
        "After a tool call returns, summarize the result and tell "
        "the user whether the action was verified."
    )

    agent = Agent(
        client=chat_client,
        instructions=instructions,
        name="genesis_phase2_adapter",
        description=(
            "Genesis Phase 2 adapter that exposes Genesis OS "
            "capabilities as Microsoft Agent Framework function "
            "tools."
        ),
        tools=tools,
    )

    return agent, adapter, tools, creds


# =========================================================
# 3. RUN THE LIVE ROUND-TRIP
# =========================================================


async def run_round_trip() -> Dict[str, Any]:
    """
    Send a real natural-language request to the agent that should
    trigger ONE of the five Phase 2 capabilities and return the
    full transcript so we can inspect it.
    """

    agent, adapter, tools, creds = await build_agent_and_tools()

    section("Live natural-language request")
    user_request = "open notepad"
    print(f"user -> model: {user_request!r}")

    start = time.monotonic()

    response = await agent.run(user_request)

    elapsed = time.monotonic() - start

    section("Model -> tool call")
    transcript: Dict[str, Any] = {
        "user_request": user_request,
        "elapsed_seconds": round(elapsed, 3),
        "creds": {
            "source": creds["source"],
            "model": creds["model"],
            "base_url": creds["base_url"],
        },
    }

    # Inspect the underlying messages on the response so the
    # transcript shows the actual function call the model emitted.
    messages = list(response.messages) if hasattr(response, "messages") else []
    transcript["num_messages"] = len(messages)
    saw_function_call = False
    saw_function_output = False
    verified_results: List[Dict[str, Any]] = []

    def _parse_tool_payload(value: Any) -> Dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if value is None:
            return None
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    for idx, msg in enumerate(messages):
        role = getattr(msg, "role", "unknown")
        print(f"  message[{idx}] role={role}")
        contents = getattr(msg, "contents", []) or []
        for c_idx, content in enumerate(contents):
            content_type = getattr(content, "type", "unknown")
            text = getattr(content, "text", None)
            call_id = getattr(content, "call_id", None)
            name = getattr(content, "name", None)
            arguments = getattr(content, "arguments", None)
            result = getattr(content, "result", None)

            preview = ""
            if text:
                preview = (text[:200] + "...") if len(text) > 200 else text
            elif arguments:
                preview = str(arguments)[:200]
            elif result:
                preview = str(result)[:200]

            print(
                f"    content[{c_idx}] type={content_type} "
                f"name={name} call_id={call_id} "
                f"preview={preview!r}"
            )

            is_call = content_type in (
                "function_call",
                "function_call_output",
                "function_result",
            ) and name is not None
            is_output = content_type in (
                "function_call_output",
                "function_result",
            )
            if is_call and content_type == "function_call":
                saw_function_call = True
            if is_output:
                saw_function_output = True
                payload = _parse_tool_payload(result)
                if payload is None:
                    payload = _parse_tool_payload(text)
                if payload is not None:
                    transcript[f"msg_{idx}_content_{c_idx}_result"] = payload
                    evidence = (payload.get("metadata") or {}).get(
                        "evidence_contract"
                    )
                    if (
                        payload.get("success") is True
                        and payload.get("verified") is True
                        and payload.get("trustworthy_success") is True
                        and isinstance(evidence, dict)
                        and evidence.get("passed") is True
                    ):
                        verified_results.append(payload)
            if content_type in (
                "function_call",
                "function_call_output",
                "function_result",
            ):
                transcript[f"msg_{idx}_content_{c_idx}"] = {
                    "type": content_type,
                    "name": name,
                    "call_id": call_id,
                    "arguments": arguments,
                    "result_preview": str(result)[:500] if result else None,
                }

    section("Final agent response text")
    final_text = (
        response.text
        if hasattr(response, "text") and response.text
        else "(no final text)"
    )
    print(final_text)
    transcript["final_text"] = final_text

    section("Verified tool result assertion")
    if verified_results:
        verified = verified_results[0]
        evidence = (verified.get("metadata") or {}).get("evidence_contract") or {}
        print("verified_result=true")
        print("verified_operation=", verified.get("operation"))
        print("verified_status=", verified.get("status"))
        print("verified_trustworthy_success=", verified.get("trustworthy_success"))
        print("evidence_passed=", evidence.get("passed"))
        print("evidence_operation=", evidence.get("operation"))
        print("evidence_metadata=", json.dumps(evidence.get("metadata") or {}, sort_keys=True))
        transcript["verified_tool_result"] = verified
    else:
        print("verified_result=false")

    section("Adapter -> ActionExecutor routing proof")
    print(
        "The five tools were registered with the live "
        "OpenAIChatCompletionClient and called by the model "
        "above.  Each tool call was routed through:\n"
        "    agent_framework_adapter._tool_call\n"
        "        -> AgentFrameworkAdapter.aexecute_capability\n"
        "        -> AgentFrameworkAdapter.execute_capability\n"
        "        -> ActionPlan (Pydantic-validated, per Phase 1)\n"
        "        -> ActionExecutor.execute (Phase 0 path)\n"
        "        -> OSManager + verification_helpers\n"
        "        -> ActionResult (real verified/verification_reason)\n"
        "    The assertion above additionally requires "
        "metadata.evidence_contract.passed=true."
    )

    transcript["saw_function_call"] = saw_function_call
    transcript["saw_function_output"] = saw_function_output
    transcript["verified_result_count"] = len(verified_results)
    transcript["ok"] = (
        saw_function_call
        and saw_function_output
        and bool(verified_results)
    )
    if not transcript["ok"]:
        raise RuntimeError(
            "The model produced a tool call, but no verified "
            "Evidence-backed ActionResult was returned."
        )
    return transcript


# =========================================================
# 4. ENTRY POINT
# =========================================================


def main() -> int:
    hr("PHASE 2 AGENT FRAMEWORK ADAPTER - LIVE VERIFICATION")
    print(
        "Proves that a real model can call a Genesis capability "
        "through Microsoft Agent Framework and receive the "
        "verified result. Uses the first available compatible "
        "AIEngine provider in backend/.env (no new credentials)."
    )

    try:
        transcript = asyncio.run(run_round_trip())
    except Exception as exc:
        hr("LIVE VERIFICATION FAILED")
        print(repr(exc))
        import traceback

        traceback.print_exc()
        return 1

    hr("LIVE VERIFICATION OK")
    print(json.dumps(transcript, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())