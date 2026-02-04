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
Following is an example of the desired banner content to be shown after each turn, next to current asky icon:
Main Model :  qf (qwen-flash) (222k ) [in: 3434, out: 2342, total: 5776 tokens] 
Summarizer :  qf (qwen-flash) (222k ) [in: 3434, out: 2342, total: 5776 tokens]
Tools : web_search[searxng]: 1 | get_url_content: 13 | get_url_details: 1 | Turns: 5/15
Messages: 14 | Sessions: 1 | Current session: "My Session Name" (14 messages, in: 123123, out: 123123, total: 123123)

- [ ] Auto HTML generation:
    - [ ] Automatically generate HTML version from Markdown after each result.
    - [ ] Support both session mode and individual message mode.
    - [ ] Save to a fixed named file in the temporary directory (overwrite on each update).
    - [ ] Display the file link in the shell for easy access (clickable link) instead of auto-opening the browser.


