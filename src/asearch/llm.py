"""LLM integration and conversation loop."""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests
from litellm import token_counter

from asearch.config import (
    LMSTUDIO,
    MAX_TURNS,
    MODELS,
    TOOLS,
    SYSTEM_PROMPT,
    FORCE_SEARCH_PROMPT,
    SYSTEM_PROMPT_SUFFIX,
    DEEP_RESEARCH_PROMPT_TEMPLATE,
    DEEP_DIVE_PROMPT_TEMPLATE,
    QUERY_SUMMARY_MAX_CHARS,
    ANSWER_SUMMARY_MAX_CHARS,
    SUMMARIZATION_MODEL,
)
from asearch.html import strip_think_tags
from asearch.tools import dispatch_tool_call, reset_read_urls


def parse_textual_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Parse tool calls from textual format (fallback for some models)."""
    if not text:
        return None
    m = re.search(r"to=functions\.([a-zA-Z0-9_]+)", text)
    if not m:
        return None
    name = m.group(1)
    j = re.search(r"(\{.*\})", text, re.S)
    if not j:
        return None
    try:
        json.loads(j.group(1))
        return {"name": name, "arguments": j.group(1)}
    except Exception:
        return None


def get_llm_msg(
    model_id: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = TOOLS
) -> Dict[str, Any]:
    """Send messages to the LLM and get a response."""
    # Find the model config based on model_id
    model_config = next((m for m in MODELS.values() if m["id"] == model_id), None)

    url = LMSTUDIO
    headers = {"Content-Type": "application/json"}

    if model_config and "base_url" in model_config:
        url = model_config["base_url"]

    api_key = None
    if model_config and "api_key" in model_config:
        api_key = model_config["api_key"]
    elif model_config and "api_key_env" in model_config:
        api_key_env_var = model_config["api_key_env"]
        api_key = os.environ.get(api_key_env_var)
        if not api_key:
            print(f"Warning: {api_key_env_var} not found in environment variables.")

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model_id,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    max_retries = 5
    backoff = 2

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]
        except requests.exceptions.HTTPError as e:
            if (
                e.response is not None
                and e.response.status_code == 429
                and attempt < max_retries - 1
            ):
                print(f"Rate limit exceeded (429). Retrying in {backoff} seconds...")
                time.sleep(backoff)
                backoff *= 2
                continue
            raise e
    raise requests.exceptions.HTTPError("Max retries exceeded")


def extract_calls(msg: Dict[str, Any], turn: int) -> List[Dict[str, Any]]:
    """Extract tool calls from an LLM message."""
    tc = msg.get("tool_calls")
    if tc:
        return tc
    parsed = parse_textual_tool_call(msg.get("content", ""))
    if parsed:
        return [{"id": f"textual_call_{turn}", "function": parsed}]
    return []


def construct_system_prompt(
    deep_research_n: int, deep_dive: bool, force_search: bool
) -> str:
    """Build the system prompt based on mode flags."""
    system_content = SYSTEM_PROMPT
    if force_search:
        system_content += FORCE_SEARCH_PROMPT
    system_content += SYSTEM_PROMPT_SUFFIX

    if deep_research_n > 0:
        system_content += DEEP_RESEARCH_PROMPT_TEMPLATE.format(n=deep_research_n)
    if deep_dive:
        system_content += DEEP_DIVE_PROMPT_TEMPLATE
    return system_content


def run_conversation_loop(
    model_config: Dict[str, Any], messages: List[Dict[str, Any]], summarize: bool
) -> str:
    """Run the multi-turn conversation loop with tool execution."""
    turn = 0
    start_time = time.perf_counter()
    final_answer = ""
    original_system_prompt = (
        messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    )

    # Reset read URLs for new conversation
    reset_read_urls()

    try:
        while turn < MAX_TURNS:
            turn += 1

            # Token & Turn Tracking
            total_tokens = token_counter(model=model_config["id"], messages=messages)
            context_size = model_config.get("context_size", 4096)
            turns_left = MAX_TURNS - turn + 1

            status_msg = (
                f"\n\n[SYSTEM UPDATE]:\n"
                f"- Context Used: {total_tokens / context_size * 100:.2f}%"
                f"- Turns Remaining: {turns_left} (out of {MAX_TURNS})\n"
                f"Please manage your context usage efficiently."
            )
            if messages and messages[0]["role"] == "system":
                messages[0]["content"] = original_system_prompt + status_msg

            msg = get_llm_msg(model_config["id"], messages)
            calls = extract_calls(msg, turn)
            if not calls:
                final_answer = strip_think_tags(msg.get("content", ""))
                print(final_answer)
                break
            messages.append(msg)
            for call in calls:
                result = dispatch_tool_call(call, model_config["max_chars"], summarize)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result),
                    }
                )
        if turn >= MAX_TURNS:
            print("Error: Max turns reached.")
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        print(f"\nQuery completed in {time.perf_counter() - start_time:.2f} seconds")
    return final_answer


def generate_summaries(query: str, answer: str) -> tuple[str, str]:
    """Generate summaries for query and answer using the summarization model."""
    query_summary = ""
    answer_summary = ""

    # Generate Query Summary (if needed)
    if len(query) > QUERY_SUMMARY_MAX_CHARS:
        try:
            msgs = [
                {
                    "role": "system",
                    "content": "Summarize the following query into a single short sentence (max 40 chars).",
                },
                {"role": "user", "content": query[:1000]},
            ]
            model_id = MODELS[SUMMARIZATION_MODEL]["id"]
            msg = get_llm_msg(model_id, msgs, tools=None)
            query_summary = strip_think_tags(msg.get("content", "")).strip()
            if len(query_summary) > QUERY_SUMMARY_MAX_CHARS:
                query_summary = query_summary[: QUERY_SUMMARY_MAX_CHARS - 3] + "..."
        except Exception as e:
            print(f"Error summarizing query: {e}")
            query_summary = query[:QUERY_SUMMARY_MAX_CHARS]

    # Generate Answer Summary (Always)
    try:
        msgs = [
            {
                "role": "system",
                "content": f"Summarize the following answer into a short paragraph (max {ANSWER_SUMMARY_MAX_CHARS} chars).",
            },
            {"role": "user", "content": answer[:5000]},
        ]
        model_id = MODELS[SUMMARIZATION_MODEL]["id"]
        msg = get_llm_msg(model_id, msgs, tools=None)
        answer_summary = strip_think_tags(msg.get("content", "")).strip()
        if len(answer_summary) > ANSWER_SUMMARY_MAX_CHARS:
            answer_summary = answer_summary[: ANSWER_SUMMARY_MAX_CHARS - 3] + "..."
    except Exception as e:
        print(f"Error summarizing answer: {e}")
        answer_summary = answer[:ANSWER_SUMMARY_MAX_CHARS]

    return query_summary, answer_summary
