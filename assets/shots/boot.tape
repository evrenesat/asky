# First run creates config (hidden); second run shows the "no model" error
Hide
Type "/bin/rm -rf /tmp/fakehome/*"
Enter
Sleep 500ms
Type "export HOME=/tmp/fakehome"
Enter
Sleep 500ms
Type 'asky hello 2>&1; true'
Enter
Wait+Screen     /config/
Type 'clear'
Sleep 300ms
Enter
Show