# TODO

- [ ] When we reach turn limit, instead of abruptly breaking the loop, make an extra call to model with all the remaining existing message history we have and tell it to
 your task. You cannot make any more tool calls.
  
- [ ] Auto HTML generation:
    - [ ] Automatically generate HTML version from Markdown after each result.
    - [ ] Support both session mode and individual message mode.
    - [ ] Save to a fixed named file in the temporary directory (overwrite on each update).
    - [ ] Display the file link in the shell for easy access (clickable link) instead of auto-opening the browser.


