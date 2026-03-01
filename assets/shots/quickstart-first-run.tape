Source assets/shots/base.tape
Output assets/shots/quickstart-first-run.gif

# Uses a fresh temp HOME so asky bootstraps config from scratch
Hide
Type "export HOME=$(mktemp -d)"
Enter
Sleep 500ms
Show

Type 'asky "hello"'
Sleep 300ms
Enter
Sleep 10s
