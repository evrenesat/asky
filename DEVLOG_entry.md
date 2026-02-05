
## 2026-02-05 - Custom Tool Enabling

**Summary**: Added an `enabled` property to custom tool configurations, allowing users to selectively enable or disable tools directly from `config.toml`.

**Changes**:
- **Core**: Updated `create_default_tool_registry` in `src/asky/core/engine.py` to skip registration of custom tools where `enabled = false`.
- **Tests**: Added a unit test in `tests/test_custom_tools.py` to verify that disabled tools are not registered.
- **Verification**: Verified with a reproduction script and the full test suite (105 passed).
