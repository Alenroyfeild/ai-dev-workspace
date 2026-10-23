---
title: Guards pack safety net
duration_hint: 45s
status: Stable
ws_version: 0.1.0b5
---
## Problem
An assistant might accidentally execute destructive commands (e.g. `rm -rf ~`, `git reset --hard`) or write secrets to tracked files.
## Steps
```sh
ws start --yes
ws pack add guards
ws start --yes
ws packs
ws pack remove guards
ws start --undo
```
## Guidance
Stable: The opt-in `guards` pack adds PreToolUse hooks to Claude Code and Codex that intercept risky tool calls before execution.
It denies dangerous patterns like `rm -rf ~`, `git reset --hard`, force pushing, `git clean -f`, API secrets in files or commands, and newly skipped tests.
Limits:
Guards are a safety net for common mistakes, not an unbypassable security boundary.
Regex pattern matching cannot interpret semantic intent or block obfuscated shell variations; normal permissions and review stay required.
Temporarily bypass guards for a single session by launching your assistant with `WS_GUARDS=off`.
## Narration
Autonomous coding assistants can make critical errors if given unrestricted terminal execution. The opt-in `guards` pack adds deterministic pre-execution checks for Claude Code and Codex. Run `ws pack add guards` and refresh with `ws start` to activate the hooks. Destructive shell commands like removing your home directory or force resetting git history are blocked immediately before they can execute. Guards act as an operational safety net for accidental commands rather than a security perimeter. You can disable or remove the pack anytime with `ws pack remove guards`.
