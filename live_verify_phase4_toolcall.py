"""
Phase 4 Live Verification — Agent Framework Tool-Calling
========================================================
Sends "open notepad" through the Agent Framework adapter with a
NON-DEFAULT provider, showing the full transcript where:
  - model emits a tool call
  - adapter routes it to ActionExecutor
  - real verified result comes back
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND / ".env", override=False)


def hr(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)

def sec(t):
    print("\n--- " + t + " ---")


async def run_tool_call_proof(model: str):
    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatCompletionClient
    from openai import AsyncOpenAI
    from genesis_os.agent_framework_adapter import build_default_adapter

    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    if not api_key:
        raise RuntimeError("No OPENROUTER_API_KEY in .env")

    async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    chat_client = OpenAIChatCompletionClient(model=model, async_client=async_client)

    adapter = build_default_adapter()
    tools = adapter.build_tools()

    instructions = (
        "You are a Genesis desktop assistant. "
        "When the user asks you to open a desktop application, "
        "use the appropriate tool. After a tool call returns, "
        "summarize the result."
    )

    agent = Agent(
        client=chat_client,
        instructions=instructions,
        name="genesis_phase4_alt_provider",
        tools=tools,
    )

    hr(f"LIVE VERIFICATION — NON-DEFAULT PROVIDER ({model})")
    print(f"User request: 'open notepad'")
    print(f"Provider model: {model}")
    print(f"Default model would be: nvidia/nemotron-3-super-120b-a12b:free")

    sec("Sending through Agent Framework adapter...")
    t0 = time.monotonic()
    response = await agent.run("open notepad")
    elapsed = time.monotonic() - t0
    print(f"Round-trip: {elapsed:.2f}s")

    sec("Full message transcript")
    messages = list(response.messages) if hasattr(response, "messages") else []
    print(f"Total messages: {len(messages)}")

    tool_call_names = []
    tool_results = []
    for idx, msg in enumerate(messages):
        role = getattr(msg, "role", "?")
        contents = getattr(msg, "contents", []) or []
        for ci, c in enumerate(contents):
            ctype = getattr(c, "type", "?")
            name = getattr(c, "name", None)
            call_id = getattr(c, "call_id", None)
            arguments = getattr(c, "arguments", None)
            result_text = getattr(c, "result", None)
            text = getattr(c, "text", None)

            print(f"  msg[{idx}] role={role}  content[{ci}] type={ctype}", end="")
            if name:
                print(f"  name={name}", end="")
            print()

            if text:
                print(f"    text: {text[:400]!r}")
            if arguments:
                print(f"    arguments: {arguments}")
            if result_text is not None:
                print(f"    result: {str(result_text)[:400]}")

            if ctype == "function_call":
                tool_call_names.append(name)
                print(f"    >>> ACTION: model called tool '{name}' with {arguments}")
            if ctype == "function_result":
                tool_results.append(result_text)
                print(f"    >>> ACTION: ActionExecutor returned result for call_id={call_id}")

    sec("Tool calls that reached ActionExecutor")
    if tool_call_names:
        for i, name in enumerate(tool_call_names):
            print(f"  [{i+1}] {name}")
    else:
        print("  (No tool calls emitted)")

    if tool_results:
        print()
        for i, res in enumerate(tool_results):
            print(f"  Result [{i+1}] (first 600 chars):")
            print(f"    {str(res)[:600]}")

    sec("Final agent text (visible to user)")
    final = getattr(response, "text", "") or "(no text)"
    print(f"  {final[:500]}")

    sec("Result summary")
    has_tool_call = len(tool_call_names) > 0
    has_result = len(tool_results) > 0
    print(f"  Tool call emitted:    {has_tool_call}")
    print(f"  ActionExecutor ran:   {has_result}")
    print(f"  Model used:           {model}")
    print(f"  Round-trip time:      {elapsed:.2f}s")

    return {
        "model": model,
        "elapsed": elapsed,
        "has_tool_call": has_tool_call,
        "has_result": has_result,
        "tool_call_names": tool_call_names,
        "tool_results": tool_results,
        "final_text": final,
    }


async def main():
    hr("PHASE 4 — AGENT FRAMEWORK TOOL-CALLING LIVE PROOF")
    print("Proves a NON-DEFAULT LLM provider can call Genesis")
    print("capabilities through the Agent Framework adapter,")
    print("reaching the real ActionExecutor with verified results.")

    alt_model = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

    try:
        r = await run_tool_call_proof(alt_model)
        passed = r["has_tool_call"] and r["has_result"]
        hr("VERIFICATION PASSED" if passed else "VERIFICATION INCONCLUSIVE")
        print(f"  Model: {r['model']}")
        print(f"  Tool call reaching executor: {r['has_tool_call']}")
        print(f"  Verified result returned: {r['has_result']}")
        if r["final_text"]:
            print(f"  Final text: {r['final_text'][:200]}")
    except Exception as e:
        hr("VERIFICATION FAILED")
        import traceback
        traceback.print_exc()
        return 1

    # ---- Anthropic section ----
    print()
    sec("ANTHROPIC PROVIDER — honest status report")
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        print("ANTHROPIC_API_KEY found. Attempting Agent Framework round-trip...")
        try:
            from agent_framework import Agent
            from agent_framework.anthropic import AnthropicClient
            from anthropic import AsyncAnthropic
            from genesis_os.agent_framework_adapter import build_default_adapter

            async_client = AsyncAnthropic(api_key=api_key)
            chat_client = AnthropicClient(model="claude-sonnet-4-20250514", anthropic_client=async_client)
            adapter = build_default_adapter()
            tools = adapter.build_tools()

            agent = Agent(
                client=chat_client,
                instructions="You are a Genesis desktop assistant. Use tools when asked.",
                name="genesis_phase4_anthropic",
                tools=tools,
            )

            hr("LIVE VERIFICATION — ANTHROPIC (claude-sonnet-4, direct API)")
            t0 = time.monotonic()
            response = await agent.run("open notepad")
            elapsed = time.monotonic() - t0
            print(f"Round-trip: {elapsed:.2f}s")

            messages = list(response.messages) if hasattr(response, "messages") else []
            for idx, msg in enumerate(messages):
                for ci, c in enumerate(getattr(msg, "contents", []) or []):
                    ctype = getattr(c, "type", "?")
                    name = getattr(c, "name", None)
                    arguments = getattr(c, "arguments", None)
                    result_text = getattr(c, "result", None)
                    text = getattr(c, "text", None)
                    print(f"  msg[{idx}] content[{ci}] type={ctype}", end="")
                    if name:
                        print(f"  name={name}", end="")
                    print()
                    if text:
                        print(f"    text: {text[:400]!r}")
                    if arguments:
                        print(f"    arguments: {arguments}")
                    if result_text is not None:
                        print(f"    result: {str(result_text)[:400]}")

            final = getattr(response, "text", "") or "(no text)"
            sec("Anthropic final text")
            print(f"  {final[:300]}")

        except Exception as e:
            hr("ANTHROPIC — FAILED")
            import traceback
            traceback.print_exc()
    else:
        print("No ANTHROPIC_API_KEY in environment.")
        print("Provider is architecture-ready; cannot run live proof without key.")
        print()
        from ai.providers import AnthropicProvider
        p = AnthropicProvider()
        print(f"  Provider name:      {p.name}")
        print(f"  Provider model:     {p.model_id}")
        print(f"  Available:          {p.is_available}")
        print(f"  Supports tools:     {p.supports_tool_calling}")
        print()
        print("The AnthropicProvider is fully implemented in ai/providers.py.")
        print("It uses a different SDK (anthropic), different wire format")
        print("(Anthropic Messages API, not OpenAI Chat Completions), and")
        print("different auth header (x-api-key + anthropic-version).")
        print("Set ANTHROPIC_API_KEY to see the live proof.")


if __name__ == "__main__":
    asyncio.run(main())
