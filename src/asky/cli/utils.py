"""CLI utility functions for asky."""

import re
import os
import pyperclip
from asky.config import USER_PROMPTS, QUERY_EXPANSION_MAX_DEPTH, MAX_PROMPT_FILE_SIZE


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def load_custom_prompts(prompt_map: dict[str, str] | None = None) -> None:
    """Read custom prompts from file path if they start with file://."""
    active_prompts = prompt_map if prompt_map is not None else USER_PROMPTS
    for key, value in active_prompts.items():
        if isinstance(value, str) and value.startswith("file://"):
            file_path = value[7:]
            path = os.path.expanduser(file_path)

            if not os.path.exists(path):
                print(f"[Warning: Custom prompt file '{path}' not found]")
                continue

            if not os.path.isfile(path):
                print(f"[Warning: Custom prompt path '{path}' is not a file]")
                continue

            # Check file size
            file_size = os.path.getsize(path)
            if file_size > MAX_PROMPT_FILE_SIZE:
                print(
                    f"[Warning: Custom prompt file '{path}' is too large ({file_size} > {MAX_PROMPT_FILE_SIZE} bytes)]"
                )
                continue

            if file_size == 0:
                print(f"[Warning: Custom prompt file '{path}' is empty]")
                continue

            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    active_prompts[key] = content
            except UnicodeDecodeError:
                print(
                    f"[Warning: Custom prompt file '{path}' is not a valid text file]"
                )
            except Exception as e:
                print(f"[Warning: Error reading custom prompt file '{path}': {e}]")


def expand_query_text(
    text: str,
    verbose: bool = False,
    prompt_map: dict[str, str] | None = None,
) -> str:
    """Recursively expand slash commands like /cp and predefined prompts."""
    active_prompts = prompt_map if prompt_map is not None else USER_PROMPTS
    expanded = text
    max_depth = QUERY_EXPANSION_MAX_DEPTH
    depth = 0

    while depth < max_depth:
        original = expanded

        # 1. Expand /cp
        if "/cp" in expanded:
            try:
                clipboard_content = pyperclip.paste()
                if clipboard_content:
                    expanded = expanded.replace("/cp", clipboard_content)
                    if verbose:
                        print("[Expanded /cp from clipboard]")
                else:
                    if verbose:
                        print("[Warning: Clipboard is empty, /cp not expanded]")
            except Exception as e:
                if verbose:
                    print(f"[Error reading clipboard: {e}]")

        # 2. Expand predefined prompts from USER_PROMPTS
        for key, prompt_val in active_prompts.items():
            pattern = rf"/{re.escape(key)}(\s|$)"
            if re.search(pattern, expanded):
                expanded = re.sub(pattern, rf"{prompt_val}\1", expanded)
                if verbose:
                    print(f"[Expanded Prompt '/{key}']")

        if expanded == original:
            break
        depth += 1

    return expanded.strip()


def print_config(
    args,
    MODELS,
    DEFAULT_MODEL,
    MAX_TURNS,
    QUERY_SUMMARY_MAX_CHARS,
    ANSWER_SUMMARY_MAX_CHARS,
) -> None:
    """Print configuration details for verbose mode."""

    print("\n=== CONFIGURATION ===")
    print(f"Selected Model: {args.model}")
    print(f"Summarize: {args.summarize}")
    print("-" * 20)

    print(f"DEFAULT_MODEL: {DEFAULT_MODEL}")
    print(f"MAX_TURNS: {MAX_TURNS}")
    print(f"QUERY_SUMMARY_MAX_CHARS: {QUERY_SUMMARY_MAX_CHARS}")
    print(f"ANSWER_SUMMARY_MAX_CHARS: {ANSWER_SUMMARY_MAX_CHARS}")
    print("-" * 20)
    print("MODELS Config:")
    for m_alias, m_conf in MODELS.items():
        print(f"  [{m_alias}]: {m_conf['id']}")
        for k, v in m_conf.items():
            if k == "id":
                continue

            # Special handling for api_key_env
            if k == "api_key_env":
                print(f"    {k}: {v}")
                # Check if env var is set
                env_val = os.environ.get(v)
                if env_val:
                    masked = (
                        env_val[:5] + "..." + env_val[-4:]
                        if len(env_val) > 10
                        else "***"
                    )
                    print(f"      [Status]: SET ({masked})")
                else:
                    print("      [Status]: NOT SET")
                continue

            if "key" in k.lower() and v and k != "api_key_env":
                # Mask key directly
                masked = v[:5] + "..." + v[-4:] if len(v) > 10 else "***"
                print(f"    {k}: {masked}")
            else:
                print(f"    {k}: {v}")
    print("=====================\n")
