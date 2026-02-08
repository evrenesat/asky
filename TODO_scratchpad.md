CRITICAL - Security

  - src/asky/tools.py:220-221 - Shell injection vulnerability: subprocess.run(cmd_str, shell=True) with user-controlled args. Should use shell=False with args # NO, we need shell=True, also we trust the user input here.

  HIGH - Potential Bugs

  - tools.py:60, 100 - Bare Exception catches without logging context
  - core/api_client.py:159-161 - HTTPError.response used without null-check
  - storage/sqlite.py:81 - init_db() called on every write (performance overhead)
  - html.py:38-47 - handle_data() adds orphaned text to links list incorrectly

  MEDIUM - Code Quality

  - cli/main.py:268-280 - Redundant history is not None check
  - cli/utils.py:92-141 - Uppercase parameter names violate PEP 8
  - summarization.py:73-74 - Duplicate comment lines
  - tools.py:123-150 - set() deduplication loses URL ordering

  LOW - Type Hints

  - cli/history.py:63-69 - Missing -> None return type
  - storage/interface.py:137, 142, 147 - Missing return type hints on abstract methods

  Test Coverage Gaps

  - No tests for shell command execution with metacharacters
  - No tests for concurrent SQLite access
  - No tests for malformed LLM JSON responses
  - No tests for max turns exit path (cli/chat.py:141-176)



  [ ] thin version of banner: 1 and 2 line versions.
  [] research on file/directory: done, needs testing.
  [ ] Insert date time to end of final results as a footnote. (except when we are in concise mode)
 


 I want to replace current research mode flow and prompting with a bit more preprocessing to be able to get better results from smaller models.
 We are also going to modify improve on normal querying.  We will start with that one because it's simpler. 
 
 in normal querying: (non-research mode)
 When user enters prompt with  URLs,
 before sending prompt to model, we are going to directly visit the URL and  to extract the main content as a markdown using (trafilatura.extract(html_string, output_format="markdown"))
 and we are going to get the same. Yeah, this is the for now this is the only change. And
 for get URL details where we also give links
 to the model we are we will use our our ag tooling
 to count sorry two two
 to rank the links that are most relevant to the query of the user of course that's only possible for short queries. But even for longer, very long user prompt, we can use our summarization model with a different summary prompt to extract questions from the user prompt. The main benefit is we assume summary model is running locally so it doesn't cost to user. So we try to benefit from that as much as possible. 

Extending tool definitions with system prompt updates.
 -------
 Right now we have hardcoded guidelines in the system prompt about how and when to use tools. This is not flexible because I want to easily disable enable
 certain tools from even command line. So we need to do a few things in order. First we should introduce another field to tool definitions also for user-defined tools of course. That the guideline we added to system prompt when the tool is
 enabled for the session or the current invocation. And the other part of that. I want easy. We exclude some tools from command line.