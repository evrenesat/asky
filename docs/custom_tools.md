# Custom Tools

You can extend asky's capabilities by defining your own custom tools in `user.toml` (or `config.toml`). These tools allow the LLM to execute local CLI commands on your machine and read their output, effectively bridging the gap between the AI's reasoning and your local environment.

> [!CAUTION]
> **Security Risk:** Custom tools execute commands using your system shell. While asky attempts to quote arguments safely, exposing powerful CLI tools to an LLM carries inherent risks. Use this feature with caution and only grant access to safe, read-only commands if possible.

## Defining a Custom Tool

Tools are defined using the `[tool.<tool_name>]` block in TOML.

### Example: Listing Directory Contents

```toml
[tool.list_dir]
command = "ls"
description = "List the contents of a directory."
enabled = true

[tool.list_dir.parameters]
type = "object"
required = ["path"]

[tool.list_dir.parameters.properties.path]
type = "string"
default = "."
```

### Example: Searching Files (grep)

```toml
[tool.grep_search]
command = "grep -r {pattern} {path}"
description = "Search for a pattern in files recursively."
enabled = false # Disabled by default for safety

[tool.grep_search.parameters]
type = "object"
required = ["pattern"]

[tool.grep_search.parameters.properties.pattern]
type = "string"
description = "The regex pattern to search for."

[tool.grep_search.parameters.properties.path]
type = "string"
description = "The directory path to search in."
default = "."
```

## How It Works

1. **Schema Generation:** asky reads your TOML blocks and translates them into an OpenAI-compatible JSON schema. This schema is included in the tool registry sent to the LLM.
2. **Placeholders:** In your `command` string, use `{param_name}` to indicate where the LLM's arguments should be injected.
   - If asky finds `{param_name}`, it replaces it with the LLM's value.
   - If asky doesn't find placeholders but arguments are provided, it safely appends them to the end of the command.
3. **Quoting and Safety:** All arguments provided by the LLM are automatically cleaned (inner double-quotes are escaped/removed) and wrapped in double-quotes to prevent shell injection attacks.
4. **Execution:** The final interpolated string is executed via the terminal shell (`subprocess.run(shell=True)`). This allows you to use advanced piping and redirection in your tool definition (e.g., `command = "cat {file} | grep {pattern}"`).
5. **Default Values:** If you define a parameter with a `default` value in the TOML configuration, it will be automatically injected into your `command` if the LLM omits it during the tool call.

## Performance Tips

When creating recursive tools like `grep` or `find`, the output can easily overwhelm the LLM's context window or cause timeout errors. Always try to limit the scope of the command in the definition:

**Good:**

```toml
command = "grep -r --exclude-dir={.venv,node_modules,.git} {pattern} {path}"
```

**Bad:**

```toml
command = "grep -r {pattern} {path}"
```

You can also use utilities like `head` to truncate massive outputs:

```toml
command = "cat {file} | head -n 500"
```
