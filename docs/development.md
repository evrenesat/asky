# Development Guide

This guide explains how to set up your environment for developing `asky` and how to use the automated tools provided in the repository.

## Auto-reloading the Daemon

When developing features for the XMPP daemon mode, you can use the `watch_daemon.sh` script to automatically restart the daemon whenever you make changes to the source code or configuration files.

### Prerequisites

The script requires `entr`, a utility for running arbitrary commands when files change.

```bash
# Install entr on macOS
brew install entr
```

### Usage

Run the script from the repository root:

```bash
./scripts/watch_daemon.sh
```

Any extra arguments passed to the script will be forwarded to the `asky --daemon` command. For example, to run the daemon with a specific model:

```bash
./scripts/watch_daemon.sh -m gf
```

The script monitors:

- All tracked files in the repository (using `git ls-files`).
- All configuration files in `~/.config/asky/*.toml`.

When any of these files are modified, `entr` will gracefully restart `asky --daemon`.

## Running Tests

Before submitting any changes, ensure all tests pass.

```bash
# Run the full test suite
pytest
```

Individual tests should be fast (under 1 second). If you add new features, please include corresponding unit tests in the `tests/` directory.
