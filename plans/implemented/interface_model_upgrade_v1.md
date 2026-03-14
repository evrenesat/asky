# [Goal Description]

Unify the [InterfacePlanner](file:///Users/evren/code/asky/src/asky/daemon/interface_planner.py#29-137) component to eliminate duplicated code and fix a silent failure regarding the `chat` action capability. 

Currently, [asky/plugins/xmpp_daemon/interface_planner.py](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/interface_planner.py) is a copied fork of [asky/daemon/interface_planner.py](file:///Users/evren/code/asky/src/asky/daemon/interface_planner.py). The system prompt asks the LLM to output `action_type: "chat"` for small talk. The plugin planner supports this, but the core planner only accepts [command](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/router.py#533-561) or [query](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/xmpp_service.py#316-359). If the LLM produces a `chat` action for the core planner, it silently falls back to [query](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/xmpp_service.py#316-359) with an error reason.

We will consolidate both to use the core planner, modify the core planner to natively support the `chat` action, delete the redundant plugin planner, and update the router to handle it properly.

### 1. Define "done"
The work is done when:
- [src/asky/plugins/xmpp_daemon/interface_planner.py](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/interface_planner.py) no longer exists.
- [src/asky/plugins/xmpp_daemon/router.py](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/router.py) imports and successfully uses `asky.daemon.interface_planner.InterfacePlanner`.
- [src/asky/plugins/xmpp_daemon/xmpp_service.py](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/xmpp_service.py) imports and successfully uses `asky.daemon.interface_planner.InterfacePlanner`.
- [src/asky/daemon/interface_planner.py](file:///Users/evren/code/asky/src/asky/daemon/interface_planner.py) defines `ACTION_CHAT = "chat"` and validates it correctly without falling back.
- Running `pytest tests/test_interface_planner.py` passes completely without regressions.

---

### 2. Constraints (What NOT to Do)
- **Do not** change the system prompt in [prompts.toml](file:///Users/evren/code/asky/src/asky/data/config/prompts.toml).
- **Do not** alter the underlying LLM call in `api_client.py`.
- **Do not** write meta-comments or "cleaning up" comments in the source code.
- **Do not** add generic `chat` handling to the core [asky/daemon/router.py](file:///Users/evren/code/asky/src/asky/daemon/router.py) yet; only ensure it validates correctly in the planner. The XMPP router requires the `chat` action branching.

---

### 3. Pin Assumptions
- **Python Version**: 3.13.
- **Testing**: We assume the existing tests in [test_interface_planner.py](file:///Users/evren/code/asky/tests/test_interface_planner.py) pass right now, and we will only add one test to verify the new `chat` action parsing.
- **Dependency Paths**: The module `asky.daemon.interface_planner` is accessible to the plugin `asky.plugins.xmpp_daemon`.

---

### 4. Sequential Atomic Steps

**Step 1. Unify core Action definitions to support chat**
- **File**: `[MODIFY] src/asky/daemon/interface_planner.py`
- Add `ACTION_CHAT = "chat"` directly under `ACTION_QUERY` (around line 14).
- Add `ACTION_CHAT` to the `VALID_ACTIONS` set.
- In [plan()](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/interface_planner.py#54-113), immediately before returning the final [InterfaceAction](file:///Users/evren/code/asky/src/asky/daemon/interface_planner.py#19-27) (around line 98), add the rule: `if action_type == ACTION_CHAT and not query_text: query_text = normalized`.
- In [__init__](file:///Users/evren/code/asky/src/asky/plugins/xmpp_daemon/interface_planner.py#33-49), add `double_verbose: bool = False` to kwargs, assign `self.double_verbose = bool(double_verbose)`. Use this flag in the `get_llm_msg()` call (pass `verbose=self.double_verbose` and `trace_context={"phase": "interface_planner", "source": "interface_planner"}`). This preserves the plugin's verbose behavior in the core module.
- **Verification**: Ensure `pytest tests/test_interface_planner.py` passes.

**Step 2. Repoint XMPP router to core planner**
- **File**: `[MODIFY] src/asky/plugins/xmpp_daemon/router.py`
- Change `from asky.plugins.xmpp_daemon.interface_planner import ACTION_COMMAND, ACTION_CHAT, InterfacePlanner` to `from asky.daemon.interface_planner import ACTION_COMMAND, ACTION_CHAT, InterfacePlanner`.
- **Verification**: Ensure no `ImportError` on loading this file.

**Step 3. Repoint XMPP service to core planner**
- **File**: `[MODIFY] src/asky/plugins/xmpp_daemon/xmpp_service.py`
- Change `from asky.plugins.xmpp_daemon.interface_planner import InterfacePlanner` to `from asky.daemon.interface_planner import InterfacePlanner`.
- **Verification**: `python -c "import asky.plugins.xmpp_daemon.xmpp_service"` should exit 0.

**Step 4. Delete the duplicated plugin planner**
- **File**: `[DELETE] src/asky/plugins/xmpp_daemon/interface_planner.py`
- Remove the file entirely from the codebase.
- **Verification**: `ls src/asky/plugins/xmpp_daemon/interface_planner.py` should return no such file.

**Step 5. Add unit test for ACTION_CHAT**
- **File**: `[MODIFY] tests/test_interface_planner.py`
- Import `ACTION_CHAT` from `asky.daemon.interface_planner`.
- Add a new test function `test_planner_parses_chat_action` mimicking [test_planner_invalid_json_falls_back_to_query](file:///Users/evren/code/asky/tests/test_interface_planner.py#63-79) but returning `{"action_type":"chat","command_text":"","query_text":"hi"}`.
- Assert `action.action_type == ACTION_CHAT` and `action.query_text == "hi"`.
- **Verification**: `pytest tests/test_interface_planner.py` passes immediately.

---

### 5. Final Verification Checklist
- [ ] Tests pass: `pytest tests/test_interface_planner.py`
- [ ] Tests pass: `pytest tests/` (full suite)
- [ ] No debug artifacts left behind
- [ ] Types are hinted
- [ ] No meta-comments added to the code
