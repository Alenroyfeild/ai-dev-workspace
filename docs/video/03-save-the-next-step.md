---
title: Save a decision and next step
duration_hint: 45s
status: Stable
ws_version: 0.1.0b5
---
## Problem
Leave a concrete next action so a fresh session can continue the task.
## Steps
```sh
ws start --yes
ws remember "Use integer cents for totals"
ws checkpoint memory-demo --status in_progress --next "Test rounding at checkout"
ws brief
ws start --undo
```
## Guidance
Stable: ws start creates and claims a task from the current branch (memory-demo here).
The brief shows the saved decision and next action.
Automatic capture is best-effort; explicitly save important decisions.
These CLI commands do not prove an assistant read the brief or followed it.
