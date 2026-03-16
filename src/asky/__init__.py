"""asky - AI-powered web search CLI with LLM tool-calling capabilities."""

__version__ = "0.4.14"

def main() -> None:
    """Run the CLI entry point with lazy import."""
    from asky.cli.main import main as cli_main

    cli_main()

__all__ = ["main", "__version__"]
