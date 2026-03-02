Source assets/shots/base.tape
Output assets/shots/quickstart-first-run.gif

# Uses a fresh temp HOME so asky bootstraps config from scratch
# First run creates config (hidden); second run shows the "no model" error
Hide
Type "/bin/rm -rf /tmp/fakehome/.*"
Enter
Sleep 500ms
Type "export HOME=/tmp/fakehome"
Enter
Type 'clear'
Sleep 300ms
Enter
Show

Type 'asky "hello"'
Sleep 300ms
Enter
Sleep 10s
