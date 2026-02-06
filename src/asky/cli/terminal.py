"""Terminal context fetching utilities."""

from rich.console import Console

from typing import Optional, Callable
import logging
import asyncio

try:
    import iterm2
except ImportError:
    iterm2 = None


logger = logging.getLogger(__name__)


async def _get_iterm_lines_async(connection, lines_to_fetch: int) -> str:
    """Async payload to fetch lines from iTerm2."""
    app = await iterm2.async_get_app(connection)
    if not app.current_terminal_window:
        logger.warning(
            "No current terminal window found (app.current_terminal_window is None)"
        )
        return ""

    window = app.current_terminal_window
    if not window.current_tab:
        logger.warning("No current tab found in window")
        return ""

    session = window.current_tab.current_session
    if not session:
        logger.warning("No current session found in tab")
        return ""

    # Grab the screen contents
    contents = await session.async_get_screen_contents()
    if not contents:
        logger.warning("Could not get screen contents (None)")
        return ""

    total_lines = contents.number_of_lines

    end_index = total_lines
    for i in range(total_lines - 1, -1, -1):
        line_text = contents.line(i).string.rstrip()
        if line_text:
            end_index = i
            break

    # Calculate start index
    start_index = max(0, end_index - lines_to_fetch - 2)

    collected_lines = []
    for i in range(start_index, end_index - 2):
        line_obj = contents.line(i)
        collected_lines.append(line_obj.string.rstrip())

    result = "\n".join(collected_lines)
    result = "\n".join(collected_lines)
    # logger.info(f"Collected {len(collected_lines)} lines of context.")
    return result


def get_terminal_context(lines_count: int) -> str:
    """Fetch the last N lines from the current terminal session.

    Currently only supports iTerm2.
    Returns empty string if not available or failed.
    """
    if iterm2 is None:
        logger.warning("iterm2 module not found. Cannot fetch terminal context.")
        return ""
    try:
        result = []

        async def main(connection):
            text = await _get_iterm_lines_async(connection, lines_count)
            result.append(text)

        try:
            # iterm2.run_until_complete handles connection logic
            iterm2.run_until_complete(main)
        except Exception as e:
            # This might fail if not running in iTerm or connection refused
            logger.warning(f"Failed to connect to iTerm2: {e}")
            return ""

        return result[0] if result else ""

    except Exception as e:
        logger.warning(f"Error fetching terminal context: {e}")
        return ""


def inject_terminal_context(
    messages: list[dict[str, str]],
    lines_count: int,
    verbose: bool = False,
    warn_on_error: bool = False,
    status_callback: Optional[Callable[[str], None]] = None,
) -> None:
    """Fetch and inject terminal context into the messages list."""
    if lines_count <= 0:
        return

    msg = f"Fetching last {lines_count} lines of terminal context..."
    if status_callback:
        status_callback(msg)
    else:
        print(f"\n[{msg}]")

    term_ctx = get_terminal_context(lines_count)

    if term_ctx:
        # Prepend to user query
        context_block = f"Terminal Context (Last {lines_count} lines):\n```\n{term_ctx}\n```\n\nQuery:\n"

        context_block = f"Terminal Context (Last {lines_count} lines):\n```\n{term_ctx}\n```\n\nQuery:\n"

        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = context_block + messages[-1]["content"]
        else:
            if verbose:
                logger.warning(
                    "Last message was NOT user role? Appending new message for context."
                )
    else:
        # Warn if explicitly requested (warn_on_error) OR if verbose debug is on.
        if warn_on_error or verbose:
            Console().print(
                "Warning: Could not fetch terminal context. Is iTerm2 installed and running?",
                style="bold yellow",
            )
