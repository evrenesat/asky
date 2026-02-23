"""Command preset parsing and expansion helpers."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Dict, List, Optional

from asky.config import COMMAND_PRESETS

PRESET_PREFIX = "\\"
PRESET_LIST_COMMAND = "\\presets"
POSITIONAL_PATTERN = re.compile(r"\$([1-9])")
ALL_ARGS_TOKEN = "$*"
UNKNOWN_PRESET_ERROR_TEMPLATE = (
    "Unknown preset '{name}'. Use \\presets to list available presets."
)


@dataclass(frozen=True)
class PresetExpansion:
    """Outcome of a preset expansion attempt."""

    matched: bool
    command_text: str = ""
    command_tokens: List[str] | None = None
    error: Optional[str] = None
    preset_name: Optional[str] = None


def list_presets_text() -> str:
    """Return a human-readable listing of configured command presets."""
    if not COMMAND_PRESETS:
        return "No command presets are configured."

    lines = ["Command Presets:"]
    for name in sorted(COMMAND_PRESETS.keys()):
        template = str(COMMAND_PRESETS.get(name, "") or "").strip()
        if not template:
            continue
        lines.append(f"  \\{name} -> {template}")
    if len(lines) == 1:
        return "No command presets are configured."
    return "\n".join(lines)


def expand_preset_invocation(raw_text: str) -> PresetExpansion:
    """Expand a first-token backslash preset into executable command tokens."""
    raw_value = str(raw_text or "")
    parse_text = raw_value
    if raw_value.lstrip().startswith(PRESET_PREFIX):
        # Preserve the leading "\" token; POSIX shlex treats it as escape otherwise.
        parse_text = PRESET_PREFIX + raw_value.lstrip()
    try:
        invocation_tokens = shlex.split(parse_text, posix=True)
    except ValueError as exc:
        return PresetExpansion(matched=False, error=f"Invalid command syntax: {exc}")

    if not invocation_tokens:
        return PresetExpansion(matched=False)

    first_token = invocation_tokens[0].strip()
    if not first_token.startswith(PRESET_PREFIX):
        return PresetExpansion(matched=False)

    if first_token == PRESET_LIST_COMMAND:
        return PresetExpansion(
            matched=True,
            command_text=PRESET_LIST_COMMAND,
            command_tokens=[PRESET_LIST_COMMAND],
            preset_name="presets",
        )

    preset_name = first_token[len(PRESET_PREFIX) :].strip()
    if not preset_name:
        return PresetExpansion(matched=False, error="Preset name is required.")

    template = str(COMMAND_PRESETS.get(preset_name, "") or "").strip()
    if not template:
        return PresetExpansion(
            matched=True,
            error=UNKNOWN_PRESET_ERROR_TEMPLATE.format(name=preset_name),
            preset_name=preset_name,
        )

    try:
        template_tokens = shlex.split(template, posix=True)
    except ValueError as exc:
        return PresetExpansion(
            matched=True,
            error=f"Invalid preset template for '{preset_name}': {exc}",
            preset_name=preset_name,
        )

    expanded_tokens = _expand_template_tokens(template_tokens, invocation_tokens[1:])
    return PresetExpansion(
        matched=True,
        command_text=shlex.join(expanded_tokens),
        command_tokens=expanded_tokens,
        preset_name=preset_name,
    )


def _expand_template_tokens(template_tokens: List[str], args: List[str]) -> List[str]:
    """Expand positional placeholders in preset template tokens."""
    expanded: List[str] = []
    referenced_positions: set[int] = set()
    used_all_args = False

    for token in template_tokens:
        if token == ALL_ARGS_TOKEN:
            expanded.extend(args)
            used_all_args = True
            continue

        def _replace_positional(match: re.Match[str]) -> str:
            index = int(match.group(1))
            referenced_positions.add(index - 1)
            if 0 <= index - 1 < len(args):
                return args[index - 1]
            return ""

        replaced = POSITIONAL_PATTERN.sub(_replace_positional, token).strip()
        if replaced:
            expanded.append(replaced)

    if not used_all_args:
        for index, value in enumerate(args):
            if index not in referenced_positions:
                expanded.append(value)

    return expanded
