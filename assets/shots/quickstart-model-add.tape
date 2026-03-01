Source assets/shots/base.tape
Output assets/shots/quickstart-model-add.gif

# Note: this records an interactive session against your actual config.
# It adds a model nicknamed "demo-gfl". Remove it from
# ~/.config/asky/models.toml after generating the GIF if you don't want it.

Type "asky --config model add"
Enter
Sleep 3s

# Select the first API provider listed
Type "1"
Enter
Sleep 1s

# Enter the model ID
Type "gemini-2.0-flash-lite"
Enter
Sleep 1s

# Accept default context size
Enter
Sleep 500ms

# Accept default shortlisting (auto)
Enter
Sleep 500ms

# Accept default image support (auto)
Enter
Sleep 500ms

# Skip all 9 parameter prompts (temperature, top_p, top_k, max_tokens,
# frequency_penalty, presence_penalty, repetition_penalty, min_p, top_a, seed)
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 300ms
Enter
Sleep 500ms

# Set nickname
Type "demo-gfl"
Enter
Sleep 1s

# Confirm save (default Yes)
Enter
Sleep 1s

# Decline all optional role assignments (4x No)
Type "n"
Enter
Sleep 300ms
Type "n"
Enter
Sleep 300ms
Type "n"
Enter
Sleep 300ms
Type "n"
Enter
Sleep 3s
