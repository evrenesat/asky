h# CLI Cleanup Plan: Remove Deprecated Direct Flags

**Objective:** Remove deprecated direct flags from `parse_args()` and rely solely on the grouped command translation layer for cleaner CLI surface.

**Status:** Ready for implementation  
**Estimated Impact:** Low risk (backward compatibility maintained via translation layer)

---

## Background

The CLI currently supports two syntaxes for the same operations:

1. **Grouped commands** (documented, preferred): `asky history list`, `asky session show S12`
2. **Direct flags** (deprecated, undocumented): `asky --history`, `asky --print-session S12`

Both work because `_translate_grouped_command_tokens()` converts grouped commands to flags before argparse processing. However, the direct flags are still registered in `parse_args()`, creating:

- Dual interface confusion
- Help text clutter
- Maintenance burden

---

## Proposed Changes

### Phase 1: Mark Flags as Suppressed (Soft Deprecation)

**Goal:** Hide deprecated flags from `--help` output while keeping them functional.

**Files to modify:**

- `src/asky/cli/main.py`

**Changes:**

1. Add `help=argparse.SUPPRESS` to all deprecated grouped-command flags:

```python
# History commands
parser.add_argument("-H", "--history", ..., help=argparse.SUPPRESS)
parser.add_argument("-pa", "--print-answer", ..., help=argparse.SUPPRESS)

# Session commands
parser.add_argument("-sh", "--session-history", ..., help=argparse.SUPPRESS)
parser.add_argument("-ps", "--print-session", ..., help=argparse.SUPPRESS)
parser.add_argument("-ss", "--sticky-session", ..., help=argparse.SUPPRESS)
parser.add_argument("-rs", "--resume-session", ..., help=argparse.SUPPRESS)
parser.add_argument("-se", "--session-end", ..., help=argparse.SUPPRESS)
parser.add_argument("-sfm", "--session-from-message", ..., help=argparse.SUPPRESS)
parser.add_argument("--reply", ..., help=argparse.SUPPRESS)

# Memory commands
parser.add_argument("--list-memories", ..., help=argparse.SUPPRESS)
parser.add_argument("--delete-memory", ..., help=argparse.SUPPRESS)
parser.add_argument("--clear-memories", ..., help=argparse.SUPPRESS)

# Corpus commands
parser.add_argument("--query-corpus", ..., help=argparse.SUPPRESS)
parser.add_argument("--summarize-section", ..., help=argparse.SUPPRESS)
parser.add_argument("--section-source", ..., help=argparse.SUPPRESS)
parser.add_argument("--section-id", ..., help=argparse.SUPPRESS)
parser.add_argument("--section-include-toc", ..., help=argparse.SUPPRESS)
parser.add_argument("--section-detail", ..., help=argparse.SUPPRESS)
parser.add_argument("--section-max-chunks", ..., help=argparse.SUPPRESS)
parser.add_argument("--query-corpus-max-sources", ..., help=argparse.SUPPRESS)
parser.add_argument("--query-corpus-max-chunks", ..., help=argparse.SUPPRESS)

# Prompts commands
parser.add_argument("-p", "--prompts", ..., help=argparse.SUPPRESS)

# Delete commands
parser.add_argument("--delete-messages", ..., help=argparse.SUPPRESS)
parser.add_argument("--delete-sessions", ..., help=argparse.SUPPRESS)
parser.add_argument("--clean-session-research", ..., help=argparse.SUPPRESS)
```

**Verification:**

```bash
asky --help | grep -E "(--history|--print-answer|--list-memories)"
# Should return nothing (flags hidden)

asky --history 10
# Should still work (backward compatibility)

asky history list 10
# Should work (preferred syntax)
```

---

### Phase 2: Add Grouped Command Help (Documentation)

**Goal:** Add help text explaining the grouped command surface.

**Files to modify:**

- `src/asky/cli/main.py`

**Changes:**

1. Update parser description to mention grouped commands:

```python
parser = argparse.ArgumentParser(
    prog="asky",
    description="""Tool-calling CLI with model selection.

Grouped Commands:
  asky history list [COUNT]           List recent queries
  asky history show <ID>              Show specific answer
  asky history delete <SELECTOR>      Delete history records

  asky session list [COUNT]           List recent sessions
  asky session show <ID|NAME>         Show session content
  asky session create <NAME>          Create new session
  asky session use <ID|NAME>          Resume session
  asky session end                    End current session
  asky session delete <SELECTOR>      Delete sessions
  asky session clean-research <ID>    Clear research data
  asky session from-message <ID>      Convert message to session

  asky memory list                    List saved memories
  asky memory delete <ID>             Delete memory
  asky memory clear                   Clear all memories

  asky corpus query <QUERY>           Query local corpus
  asky corpus summarize [SECTION]     Summarize corpus section

  asky prompts list                   List user prompts

  asky persona <subcommand>           Manage personas

Use 'asky <noun> <action> --help' for command-specific options.
""",
    formatter_class=argparse.RawTextHelpFormatter,
)
```

2. Add a custom help action that prints grouped command help:

```python
def _print_grouped_commands_help():
    """Print help for grouped commands."""
    print("""
Grouped Commands:

History:
  asky history list [COUNT]           List recent queries (default 10)
  asky history show <ID>              Show full answer for history ID
  asky history delete <SELECTOR>      Delete history records
  asky history delete --all           Delete all history

Session:
  asky session list [COUNT]           List recent sessions (default 10)
  asky session show <ID|NAME>         Show session content
  asky session create <NAME>          Create and activate new session
  asky session use <ID|NAME>          Resume existing session
  asky session end                    Detach from current session
  asky session delete <SELECTOR>      Delete session records
  asky session delete --all           Delete all sessions
  asky session clean-research <ID>    Clear research data for session
  asky session from-message <ID>      Convert history message to session
  asky session from-message last      Convert last message to session

Memory:
  asky memory list                    List all saved user memories
  asky memory delete <ID>             Delete specific memory by ID
  asky memory clear                   Delete all memories (with confirmation)

Corpus:
  asky corpus query <QUERY>           Query cached research corpus
  asky corpus summarize [SECTION]     List or summarize corpus sections
    Options:
      --section-source <SOURCE>       Specify corpus source
      --section-id <ID>               Exact section ID
      --section-detail <LEVEL>        Detail level (compact|balanced|max)
      --section-include-toc           Include TOC sections in listing
      --section-max-chunks <N>        Limit input chunks

Prompts:
  asky prompts list                   List configured user prompts

Persona:
  asky persona create <NAME>          Create new persona
  asky persona list                   List available personas
  asky persona load <NAME>            Load persona into session
  (see 'asky persona --help' for full subcommands)

Examples:
  asky history list 20
  asky session show S12
  asky memory list
  asky corpus query "what is the main thesis?"
  asky prompts list
""")
```

---

### Phase 3: Remove Direct Flags (Hard Deprecation)

**Goal:** Fully remove deprecated flags from parser (breaking change for direct flag users).

**Timing:** After Phase 1 has been in production for at least one release cycle.

**Files to modify:**

- `src/asky/cli/main.py`

**Changes:**

1. Remove all `parser.add_argument()` calls for deprecated flags
2. Remove corresponding handler code in `main()` that checks for these flags
3. Keep translation layer intact (grouped commands still work)

**Verification:**

```bash
asky --history 10
# Should fail with "unrecognized arguments: --history"

asky history list 10
# Should work (only supported syntax)
```

---

## Flags to Keep (Not Deprecated)

These flags are NOT part of grouped commands and should remain:

**Query modifiers:**

- `-m` / `--model`
- `-r` / `--research`
- `-s` / `--summarize`
- `-L` / `--lean`
- `-t` / `--turns`
- `-c` / `--continue-chat`
- `-em` / `--elephant-mode`
- `-tl` / `--terminal-lines`
- `-sp` / `--system-prompt`
- `-v` / `--verbose` / `-vv`
- `-o` / `--open`
- `--shortlist`
- `--tools`
- `-off` / `--tool-off`

**Configuration:**

- `--config <domain> <action>`

**Process control:**

- `--daemon`
- `--browser`

**Utility:**

- `--completion-script`
- `--list-tools`
- `--all` (modifier for delete commands)

---

## Completion Script Updates

**Files to modify:**

- `src/asky/cli/completion.py`

**Changes:**

1. Update completion functions to suggest grouped commands instead of flags:

```python
# Before:
complete --history
complete --print-answer

# After:
complete history list
complete history show
```

2. Add noun-level completion:

```python
def complete_grouped_nouns(prefix, parsed_args, **kwargs):
    """Complete grouped command nouns."""
    nouns = ["history", "session", "memory", "corpus", "prompts", "persona"]
    return [n for n in nouns if n.startswith(prefix)]

def complete_grouped_actions(prefix, parsed_args, **kwargs):
    """Complete grouped command actions based on noun."""
    # Extract noun from parsed_args or command line
    # Return valid actions for that noun
    pass
```

---

## Documentation Updates

**Files to modify:**

- `docs/configuration.md` §13
- `README.md` (if it mentions CLI commands)

**Changes:**

1. Remove all references to direct flags (`--history`, `--print-answer`, etc.)
2. Show only grouped command syntax in examples
3. Add a "Deprecated Syntax" note if needed for migration guidance

---

## Migration Guide (for users)

Create `docs/cli-migration.md`:

```markdown
# CLI Migration Guide: Direct Flags → Grouped Commands

## Overview

Direct flag syntax is deprecated in favor of grouped commands.

## Migration Table

| Old (Deprecated)               | New (Preferred)              |
| ------------------------------ | ---------------------------- |
| `asky --history 20`            | `asky history list 20`       |
| `asky --print-answer 42`       | `asky history show 42`       |
| `asky --delete-messages 42`    | `asky history delete 42`     |
| `asky --session-history 10`    | `asky session list 10`       |
| `asky --print-session S12`     | `asky session show S12`      |
| `asky --sticky-session MyProj` | `asky session create MyProj` |
| `asky --resume-session S12`    | `asky session use S12`       |
| `asky --session-end`           | `asky session end`           |
| `asky --delete-sessions S12`   | `asky session delete S12`    |
| `asky --list-memories`         | `asky memory list`           |
| `asky --delete-memory 5`       | `asky memory delete 5`       |
| `asky --clear-memories`        | `asky memory clear`          |
| `asky --query-corpus "..."`    | `asky corpus query "..."`    |
| `asky --summarize-section`     | `asky corpus summarize`      |
| `asky --prompts`               | `asky prompts list`          |

## Timeline

- **v1.x**: Both syntaxes work (direct flags hidden from help)
- **v2.0**: Direct flags removed (grouped commands only)
```

---

## Testing Checklist

### Phase 1 (Soft Deprecation)

- [ ] `asky --help` does not show deprecated flags
- [ ] `asky --help-all` still shows deprecated flags (for power users)
- [ ] `asky --history 10` still works (backward compatibility)
- [ ] `asky history list 10` works (preferred syntax)
- [ ] All grouped command translations work correctly
- [ ] Completion script suggests grouped commands
- [ ] Documentation shows only grouped commands

### Phase 2 (Documentation)

- [ ] Parser description includes grouped command help
- [ ] Custom help action prints grouped command reference
- [ ] Migration guide is clear and complete

### Phase 3 (Hard Deprecation)

- [ ] `asky --history 10` fails with clear error
- [ ] `asky history list 10` still works
- [ ] No references to deprecated flags in codebase
- [ ] All tests updated to use grouped commands
- [ ] Release notes mention breaking change

---

## Rollback Plan

If Phase 3 causes issues:

1. Revert flag removal commits
2. Keep flags suppressed (Phase 1 state)
3. Extend deprecation period
4. Add warning messages when deprecated flags are used

---

## Implementation Order

1. **Phase 1** (Low risk, immediate benefit)
   - Suppress deprecated flags from help
   - Update documentation to show grouped commands only
   - Add migration guide

2. **Phase 2** (Enhancement)
   - Add grouped command help text
   - Update completion scripts

3. **Phase 3** (Breaking change, requires major version bump)
   - Remove deprecated flags entirely
   - Clean up handler code
   - Update all tests
