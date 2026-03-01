Source assets/shots/base.tape
Output assets/shots/daemon-start.gif

# Runs the daemon in foreground mode (non-macOS path, or macOS without rumps).
# On macOS with rumps installed this launches the menubar app instead.
# Interrupt after a few seconds to stop recording.
Type "asky --daemon"
Sleep 300ms
Enter
Sleep 8s
Ctrl+C
Sleep 2s
