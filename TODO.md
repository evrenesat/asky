# TODO

- [ ] Overhaul `show_banner` in `cli/main.py`
    - [ ] Refactor to inject configuration dependency instead of reading global `MODELS` variable.
    - [ ] Implement in-place redrawing of the banner after each turn to avoid scrolling.
    - [ ] Update Session Information:
        - [ ] Display active session name (if applicable).
        - [ ] Display total count of sessions in the database.
        - [ ] Total tokens used in the current session.
        - [ ] Rename "records" label to "messages" (e.g., "15 messages").
    - [ ] Update Model & Context Display:
        - [ ] Replace vague context integers with the model's maximum context size next to the model name.
    - [ ] Integrate Real-time Statistics:
        - [ ] Move token usage reporting from new lines into the banner.
        - [ ] Report tool calls: list active tools and their usage counts in the current process.
        - [ ] Display session-wide token usage statistics from the database when in session mode.
    - [ ] Support Mode-Specific Layouts:
        - [ ] Differentiate information displayed for "session-based" mode vs. "multi-turn communication" mode.

- [ ] 
