"""LLM integration and conversation loop."""

import logging
import json
import os
import re
import tempfile
import time
import webbrowser
from typing import Any, Dict, List, Optional

import requests
from rich.console import Console
from rich.markdown import Markdown

logger = logging.getLogger(__name__)


from asky.config import (
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
    LLM_USER_AGENT,
    SUMMARIZE_QUERY_PROMPT_TEMPLATE,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
    REQUEST_TIMEOUT,
    DEFAULT_CONTEXT_SIZE,
    CONTINUE_QUERY_THRESHOLD,
)
from asky.html import strip_think_tags
from asky.tools import dispatch_tool_call, reset_read_urls


def is_markdown(text: str) -> bool:
    """Check if the text likely contains markdown formatting."""
    # Basic detection: common markdown patterns
    patterns = [
        r"^#+\s",  # Headers
        r"\*\*.*\*\*",  # Bold
        r"__.*__",  # Bold
        r"\*.*\* ",  # Italic
        r"_.*_",  # Italic
        r"\[.*\]\(.*\)",  # Links
        r"```",  # Code blocks
        r"^\s*[-*+]\s",  # Lists
        r"^\s*\d+\.\s",  # Numbered lists
    ]
    return any(re.search(p, text, re.M) for p in patterns)


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


class UsageTracker:
    """Track token usage per model alias."""

    def __init__(self):
        self.usage: Dict[str, int] = {}

    def add_usage(self, model_alias: str, tokens: int):
        self.usage[model_alias] = self.usage.get(model_alias, 0) + tokens

    def get_total_usage(self, model_alias: str) -> int:
        return self.usage.get(model_alias, 0)


def count_tokens(messages: List[Dict[str, Any]]) -> int:
    """Naive token counting: chars / 4."""
    total_chars = 0
    for m in messages:
        content = m.get("content")
        if content:
            total_chars += len(content)
        # Also count tool calls and results
        tc = m.get("tool_calls")
        if tc:
            total_chars += len(json.dumps(tc))
    return total_chars // 4


def get_llm_msg(
    model_id: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict]] = TOOLS,
    verbose: bool = False,
    model_alias: Optional[str] = None,
    usage_tracker: Optional[UsageTracker] = None,
) -> Dict[str, Any]:
    """Send messages to the LLM and get a response."""
    # Find the model config based on model_id
    model_config = next((m for m in MODELS.values() if m["id"] == model_id), None)

    url = ""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": LLM_USER_AGENT,
    }

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

    max_retries = 10
    backoff = 2
    max_backoff = 60

    logger.info(f"Sending request to LLM: {model_id}")
    logger.debug(f"Tools enabled: {bool(tools)}")

    if verbose:
        print(f"\n[DEBUG] Sending to LLM ({model_id})...")
        print(f"Tools enabled: {bool(tools)}")
        print("Last message sent:")
        if messages:
            last_msg = messages[-1]
            content = last_msg.get("content", "")
            if content and len(content) > 500:
                print(f"  Role: {last_msg['role']}")
                print(f"  Content (truncated): {content[:500]}...")
            else:
                print(f"  {json.dumps(last_msg, indent=2)}")
        print("-" * 20)

    tokens_sent = count_tokens(messages)
    log_msg = f"[{model_alias or model_id}] Sent: {tokens_sent} tokens"
    logger.info(log_msg)
    print(log_msg)

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            resp_json = resp.json()

            # Extract usage if available, otherwise use naive count
            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", tokens_sent)
            completion_tokens = usage.get("completion_tokens", 0)
            if "completion_tokens" not in usage:
                completion_tokens = (
                    len(json.dumps(resp_json["choices"][0]["message"])) // 4
                )

            total_call_tokens = prompt_tokens + completion_tokens

            if usage_tracker and model_alias:
                usage_tracker.add_usage(model_alias, total_call_tokens)

            return resp_json["choices"][0]["message"]
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                if attempt < max_retries - 1:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            # Handle potential floating point strings (e.g. "5.0")
                            wait_time = int(float(retry_after))
                        except ValueError:
                            wait_time = backoff
                            backoff = min(backoff * 2, max_backoff)
                    else:
                        wait_time = backoff
                        backoff = min(backoff * 2, max_backoff)

                    print(
                        f"Rate limit exceeded (429). Retrying in {wait_time} seconds..."
                    )
                    time.sleep(wait_time)
                    continue
            raise e
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"Request error: {e}. Retrying in {backoff} seconds...")
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue
            raise e
    raise requests.exceptions.RequestException("Max retries exceeded")


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
    model_config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    summarize: bool,
    verbose: bool = False,
    usage_tracker: Optional[UsageTracker] = None,
    open_browser: bool = False,
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
            logger.info(f"Starting turn {turn}/{MAX_TURNS}")

            # Token & Turn Tracking
            total_tokens = count_tokens(messages)
            context_size = model_config.get("context_size", DEFAULT_CONTEXT_SIZE)
            turns_left = MAX_TURNS - turn + 1

            status_msg = (
                f"\n\n[SYSTEM UPDATE]:\n"
                f"- Context Used: {total_tokens / context_size * 100:.2f}%"
                f"- Turns Remaining: {turns_left} (out of {MAX_TURNS})\n"
                f"Please manage your context usage efficiently."
            )
            if messages and messages[0]["role"] == "system":
                messages[0]["content"] = original_system_prompt + status_msg

            msg = get_llm_msg(
                model_config["id"],
                messages,
                verbose=verbose,
                model_alias=model_config.get("alias"),
                usage_tracker=usage_tracker,
            )
            calls = extract_calls(msg, turn)
            if not calls:
                final_answer = strip_think_tags(msg.get("content", ""))
                if is_markdown(final_answer):
                    console = Console()
                    console.print(Markdown(final_answer))
                else:
                    print(final_answer)

                if open_browser:
                    render_to_browser(final_answer)
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


def render_to_browser(content: str) -> None:
    """Render markdown content in a browser using a template."""
    try:
        from asky.config import TEMPLATE_PATH

        if not TEMPLATE_PATH.exists():
            print(f"Error: Template not found at {TEMPLATE_PATH}")
            return

        with open(TEMPLATE_PATH, "r") as f:
            template = f.read()

        # Escape backticks for JS template literal
        safe_content = content.replace("`", "\\`").replace("${", "\\${")

        html_content = template.replace("{{CONTENT}}", safe_content)

        with tempfile.NamedTemporaryFile(
            "w", delete=False, suffix=".html", prefix="temp_asky_"
        ) as f:
            f.write(html_content)
            temp_path = f.name

        print(f"[Opening browser: {temp_path}]")
        webbrowser.open(f"file://{temp_path}")
    except Exception as e:
        print(f"Error rendering to browser: {e}")


def generate_summaries(
    query: str, answer: str, usage_tracker: Optional[UsageTracker] = None
) -> tuple[str, str]:
    """Generate summaries for query and answer using the summarization model."""
    query_summary = ""
    answer_summary = ""

    # Generate Query Summary (if needed)
    if len(query) > CONTINUE_QUERY_THRESHOLD:
        try:
            msgs = [
                {
                    "role": "system",
                    "content": SUMMARIZE_QUERY_PROMPT_TEMPLATE.format(
                        QUERY_SUMMARY_MAX_CHARS=QUERY_SUMMARY_MAX_CHARS
                    ),
                },
                {"role": "user", "content": query[:1000]},
            ]
            model_id = MODELS[SUMMARIZATION_MODEL]["id"]
            model_alias = MODELS[SUMMARIZATION_MODEL].get("alias", SUMMARIZATION_MODEL)
            msg = get_llm_msg(
                model_id,
                msgs,
                tools=None,
                model_alias=model_alias,
                usage_tracker=usage_tracker,
            )
            query_summary = strip_think_tags(msg.get("content", "")).strip()

            logger.debug(f"Query Summary: {query_summary}")

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
                "content": SUMMARIZE_ANSWER_PROMPT_TEMPLATE.format(
                    ANSWER_SUMMARY_MAX_CHARS=ANSWER_SUMMARY_MAX_CHARS
                ),
            },
            {"role": "user", "content": answer[:5000]},
        ]
        model_id = MODELS[SUMMARIZATION_MODEL]["id"]
        model_alias = MODELS[SUMMARIZATION_MODEL].get("alias", SUMMARIZATION_MODEL)
        msg = get_llm_msg(
            model_id,
            msgs,
            tools=None,
            model_alias=model_alias,
            usage_tracker=usage_tracker,
        )
        answer_summary = strip_think_tags(msg.get("content", "")).strip()

        logger.debug(f"Answer : {answer}")
        logger.debug(f"Answer Summary: {answer_summary}")

        if len(answer_summary) > ANSWER_SUMMARY_MAX_CHARS:
            answer_summary = answer_summary[: ANSWER_SUMMARY_MAX_CHARS - 3] + "..."
    except Exception as e:
        print(f"Error summarizing answer: {e}")
        answer_summary = answer[:ANSWER_SUMMARY_MAX_CHARS]

    return query_summary, answer_summary
