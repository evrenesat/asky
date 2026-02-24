# Plan: XMPP Help Command Regression + Command Routing Fix

## Overview

Two symptoms, one root cause:

1. `/help` (and `/h`) shows only prompt aliases instead of full help text.
2. The response takes 1+ second instead of being instant.

**Root cause:** In `router.py::handle_text_message`, when `interface_planner.enabled` is `True`, the code unconditionally sends all non-prefixed messages through the LLM planner. The short-circuit path (`_looks_like_command`) that correctly identifies `/help`, `/h`, `transcript`, `-H`, etc. as direct commands is only called in the **non-planner** branch. The planner branch only short-circuits messages starting with `command_prefix` (e.g. `/asky`).

So `/help` with an active interface model hits the LLM → costs 1+ second → if LLM returns `action_type="query"`, the message goes through `execute_query_text` → `_prepare_query_text` → sees `/help` as a slash-prompt prefix → returns `_render_prompt_list(filter_prefix="help")` which is prompt aliases only.

**Current code path (broken):**
```
/help arrives → interface_planner.enabled=True
  → does NOT start with "/asky" prefix
  → interface_planner.plan("/help")    ← LLM API call, 1+ sec
  → if planner returns action_type="query"
     → execute_query_text("/help")
        → _prepare_query_text("/help")
           → expanded_query starts with "/"
              → "help" not in prompt_map
                 → _render_prompt_list(filter_prefix="help")  ← WRONG: shows aliases only
```

**Expected code path (correct):**
```
/help arrives → interface_planner.enabled=True
  → _looks_like_command("/help") is True
     → execute_command_text("/help")
        → tokens[0] in HELP_COMMAND_TOKENS
           → build_help_text()  ← CORRECT: returns full help
```

---

## Phase 1: Fix the Routing Bug

**File:** `src/asky/daemon/router.py`

**What exists now** (lines 138–158 in `handle_text_message`):
```python
if self.interface_planner.enabled:
    if self.command_prefix and text.startswith(self.command_prefix):
        command_text = text[len(self.command_prefix):].strip()
        if not command_text:
            return "Error: command body is required after prefix."
        return self.command_executor.execute_command_text(
            jid=actor_jid,
            command_text=command_text,
            room_jid=normalized_room or None,
        )
    action = self.interface_planner.plan(text)
    if action.action_type == ACTION_COMMAND:
        return self.command_executor.execute_command_text(...)
    return self.command_executor.execute_query_text(...)
```

**What it should look like after the fix** — insert a `_looks_like_command` short-circuit **between** the prefix check and the planner call:
```python
if self.interface_planner.enabled:
    if self.command_prefix and text.startswith(self.command_prefix):
        command_text = text[len(self.command_prefix):].strip()
        if not command_text:
            return "Error: command body is required after prefix."
        return self.command_executor.execute_command_text(
            jid=actor_jid,
            command_text=command_text,
            room_jid=normalized_room or None,
        )
    if _looks_like_command(text):                          # ← NEW
        return self.command_executor.execute_command_text( # ← NEW
            jid=actor_jid,                                 # ← NEW
            command_text=text,                             # ← NEW
            room_jid=normalized_room or None,              # ← NEW
        )                                                  # ← NEW
    action = self.interface_planner.plan(text)
    if action.action_type == ACTION_COMMAND:
        return self.command_executor.execute_command_text(...)
    return self.command_executor.execute_query_text(...)
```

**Constraints:**
- Do NOT change behavior for the non-planner branch (lines 161–172) — it already calls `_looks_like_command` correctly.
- Do NOT change `_looks_like_command` — it already covers `/help`, `/h`, `transcript`, `-H`, `/session`, and all the expected command tokens.
- Do NOT change `execute_command_text` — it correctly handles `/help`/`/h` via `HELP_COMMAND_TOKENS`.
- This is a 5-line addition only. No other logic changes.

**Verification:** After fix, these must all be true:
- Router with planner enabled: `/h` and `/help` → call `execute_command_text`, NOT `interface_planner.plan`
- Router with planner enabled: `transcript list` → call `execute_command_text`, NOT `interface_planner.plan`
- Router with planner enabled: `-H 5` → call `execute_command_text`, NOT `interface_planner.plan`
- Router with planner enabled: "what is the weather" (natural language) → still calls `interface_planner.plan`
- Router without planner: behavior unchanged

---

## Phase 2: Add Regression Tests

**File:** `tests/test_xmpp_router.py`

Add the following tests **after** the existing `test_router_prefixed_command_with_interface_enabled` test:

1. **`test_router_help_command_bypasses_planner_with_interface_enabled`**
   - Build router with `interface_enabled=True`
   - Send `/h` → assert response is `"command:/h:-"` (went to `execute_command_text`)
   - Assert `planner.actions` is empty (planner was NOT called)

2. **`test_router_help_long_form_bypasses_planner_with_interface_enabled`**
   - Build router with `interface_enabled=True`
   - Send `/help` → assert response is `"command:/help:-"`
   - Assert `planner.actions` is empty

3. **`test_router_transcript_command_bypasses_planner_with_interface_enabled`**
   - Build router with `interface_enabled=True`
   - Send `"transcript list"` → assert response is `"command:transcript list:-"`
   - Assert `planner.actions` is empty

4. **`test_router_flag_command_bypasses_planner_with_interface_enabled`**
   - Build router with `interface_enabled=True`
   - Send `"-H 5"` → assert response is `"command:-H 5:-"`
   - Assert `planner.actions` is empty

5. **`test_router_natural_language_still_goes_through_planner`**
   - Build router with `interface_enabled=True`
   - Send `"what is the news today"` → assert planner was called (planner.actions non-empty)

**Constraint:** Each test must access `router.interface_planner.actions` (the fake planner in the test file already records calls in `self.actions`). No changes needed to `_FakePlanner` or `_FakeCommandExecutor`.

---

## Final Checklist

- [ ] `router.py` has only the 5-line insertion; no other changes
- [ ] All existing tests in `test_xmpp_router.py` still pass
- [ ] All existing tests in `test_xmpp_commands.py` still pass
- [ ] New tests: `/h` + `/help` → `execute_command_text`, planner NOT called
- [ ] New tests: `transcript list`, `-H 5` → `execute_command_text`, planner NOT called
- [ ] New test: natural language → planner IS called
- [ ] No debug artifacts, no commented-out code
- [ ] DEVLOG.md updated

## Notes

- `_looks_like_command` is a module-level function in `router.py` — it is already imported/referenced in `test_xmpp_commands.py`. No changes needed there.
- The fix makes the interface planner focus solely on genuinely ambiguous natural-language messages, which is its intended purpose.
- No changes needed to `command_executor.py`, `interface_planner.py`, or any other file.
