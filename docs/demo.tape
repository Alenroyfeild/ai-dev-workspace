# Maintainer: run `vhs docs/demo.tape` from the source checkout root.
# Requires an existing VHS setup; this tape never installs anything.
# Syntax: https://github.com/charmbracelet/vhs#vhs-command-reference
# Offline Claude -> Codex handoff illustration, not live client-session proof.
# Target ~20s: 1s lead-in + typing/runtime + 18s hold; inspect the render.
Output docs/demo.gif
Require bash
Require python3
Set Shell bash
Set Width 1080
Set Height 620
Set FontSize 22
Set Padding 20
Set TypingSpeed 100 ms

Hide
Type `unset WS_ROOT; export WS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1; ws() { python3 -B bin/ws "$@"; }; PS1='$ '; printf '\033[2J\033[HClaude -> Codex handoff (offline simulation)\nNo live assistant sessions\n\n'`
Enter
Sleep 500 ms
Show
Sleep 1 s
Type "ws demo"
Enter
Wait+Screen /No assistant was started/
Sleep 18 s
