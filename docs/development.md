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

Any extra arguments passed to the script will be forwarded to the daemon command. For example, to run the daemon with a specific model:

```bash
./scripts/watch_daemon.sh -m gf
```

The script monitors:

- All tracked files in the repository (using `git ls-files`).
- All configuration files in `~/.config/asky/*.toml`.

When any of these files are modified, `entr` will gracefully restart the daemon in foreground mode (`asky --daemon --foreground`).

## Running Tests

Before submitting any changes, ensure all tests pass.

```bash
# Run the full test suite
pytest
```

Individual tests should be fast (under 1 second). If you add new features, please include corresponding unit tests in the `tests/` directory.

## Releasing

Package releases are handled by GitHub Actions instead of the old local `build` + `twine upload` shell flow.

Release flow:

1. Bump `[project].version` in `pyproject.toml`.
2. Push that change to `main`.
3. The `Publish package` workflow compares the current `pyproject.toml` version with `HEAD^`.
4. If the version changed, the workflow runs `uv run pytest -q`, builds `dist/*` with `uv build`, creates or updates GitHub Release `v<version>`, uploads the wheel and sdist assets, and publishes the same files to PyPI.

The workflow is rerun-safe:

- GitHub Release assets are uploaded with `gh release upload --clobber`.
- PyPI publishing uses `skip-existing: true`.
- Build contents are explicitly trimmed in `pyproject.toml` so release artifacts do not carry root docs, plans, devlogs, hidden tool directories, tests, or package-internal `AGENTS.md` files.

Before the first automated release, configure PyPI Trusted Publishing for this repository:

1. In PyPI, add a trusted publisher for GitHub repository `evrenesat/asky`.
2. Point it at workflow `.github/workflows/publish-package.yml`.
3. Use environment name `pypi`.

Once that is in place, you do not need a `PYPI_API_TOKEN` secret for the workflow.
