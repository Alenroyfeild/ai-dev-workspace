---
title: Stop retrying dead ends
duration_hint: 45s
status: Stable
ws_version: 0.1.0b5
---
## Problem
An assistant in a fresh session repeats a failed approach or broken implementation unless informed.
## Steps
```sh
ws start --yes
ws checkpoint --status in_progress --next "Use rate limiting header" --note "Do not redo=Session cookies break mobile clients"
ws brief
ws start --undo
```
## Guidance
Stable: `ws checkpoint` accepts `--note "Do not redo=<text>"`, which displays under `Do not redo:` in every fresh session brief.
Claude Code and Codex (live-tested) receive these at session start; other connected assistants are fixture-tested.
Limits:
Only dead ends recorded in the task record appear in the startup brief; unrecorded failed attempts cannot be anticipated.
The brief is prompt context, not an execution lock; an assistant could still retry a failed command if instructed.
Dead-end capture from unstructured conversation cues is best-effort; explicit checkpoints are deterministic.
## Narration
When an AI assistant starts a fresh session, it does not know what you tried and discarded yesterday. Save failed experiments into your task checkpoint using the Do not redo section. The startup brief highlights these dead ends directly beneath your next action, so the assistant avoids repeating known mistakes. When you are done exploring, running `ws start --undo` safely detaches hooks and excludes without modifying your code.
