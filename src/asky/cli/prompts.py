"""Prompt-related CLI commands for asky."""

from asky.config import USER_PROMPTS


def list_prompts_command() -> None:
    """List all configured user prompts."""
    if not USER_PROMPTS:
        print("\nNo user prompts configured.")
        return

    print("\nConfigured User Prompts:")
    print("-" * 40)
    for alias, prompt in USER_PROMPTS.items():
        print(
            f"[{alias}]: {prompt[:100]}..."
            if len(prompt) > 100
            else f"[{alias}]: {prompt}"
        )
    print("-" * 40)
