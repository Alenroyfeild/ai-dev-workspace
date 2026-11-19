---
title: Claim the next task
duration_hint: 45s
status: Preview
ws_version: 0.2.0
---
## Problem
Two workers asking "what is next?" can pick the same task if choosing and claiming are separate steps.
## Steps
```sh
ws start --yes
ws task new T-1 "First task"
ws task new T-2 "Second task"
ws task next
ws task list
ws start --undo
```
## Guidance
Preview (Experimental command, outside the 1.0 promise): `ws task next` picks the first eligible unclaimed task and claims it in one locked step, then prints the task and its claim token. The MCP tool is `claim_next_task`.
Eligible means not done or blocked, not already claimed and with every dependency done; in_progress comes first, then review, ready and backlog.
Limits:
Claims do not expire automatically; after confirming the owner has stopped, recover with `ws release ID --worker OWNER --token TOKEN`.
If no task is eligible the command fails with "No eligible unclaimed tasks."
## Narration
When several workers pull from the same list, choosing and claiming must be one step. The next-task command picks the first eligible unclaimed task under the workspace lock and claims it for you, so two workers cannot take the same one. Tasks whose dependencies are not done are skipped. Claims do not expire by themselves, so release a stale one by hand. This is experimental and may change.
