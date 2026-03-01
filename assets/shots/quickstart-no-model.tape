Source assets/shots/base.tape
Output assets/shots/quickstart-no-model.gif

# First run creates config (hidden); second run shows the "no model" error
Hide
Type "export HOME=$(mktemp -d)"
Enter
Sleep 500ms
Type 'asky "hello" 2>&1; true'
Enter
Sleep 10s
Show

Type 'asky "hello"'
Sleep 300ms
Enter
Sleep 8s
