#!/bin/bash

# watch_daemon.sh
# Restarts AskyDaemon whenever repository files or configuration files change.
# Depends on 'entr' (http://eradman.com/entrproject/)

set -e

if ! command -v entr >/dev/null 2>&1; then
  echo "Error: 'entr' is not installed." >&2
  echo "Install it via Homebrew: brew install entr" >&2
  exit 1
fi

# Use a subshell to avoid affecting the caller's directory.
(
  # Move to the repository root.
  cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

  echo "Watching for changes in repository and ~/.config/asky/..."

  # 1. Gather repository files (*.py, *.toml, *.md, etc.)
  # 2. Gather user config files (~/.config/asky/*.toml)
  # 3. Pipe everything to entr to restart 'asky --daemon'
  
  {
    git ls-files
    ls ~/.config/asky/*.toml 2>/dev/null || true
  } | entr -r -d -- asky --daemon "$@"
)
