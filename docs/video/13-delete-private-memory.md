---
title: Remove a repo and its memory
duration_hint: 45s
status: Stable
ws_version: 0.2.0
---
## Problem
Leaving the workflow used to keep private memory forever unless you removed the folder by hand.
## Steps
```sh
ws start --yes
ws start --undo --delete-memory --yes
```
## Guidance
Stable: `ws start --undo --delete-memory` undoes the repo wiring, then names the exact private workspace recorded for this repo and the number of task files, and asks `[y/N]`. `--yes` skips the question; closed input or "n" keeps everything, wiring included.
It refuses when another repo is still wired to the workspace, when the workspace contains symlinks, and when the path is your home folder, a parent of it, the repo or the kit. A plain `ws start --undo` still keeps memory.
Limits:
The deletion removes the whole workspace folder, including notes you added to its vault; the preview shows the task count, not every file.
The Windows path is tested only in CI.
## Narration
Zero point two lets you leave cleanly. Add the delete-memory flag to undo and ws shows the exact workspace it recorded for this repo, counts the task files, and asks before removing anything. Say no and everything stays, wiring included. It refuses when another repo still uses the workspace or when the folder holds symlinks. The deletion takes the whole folder, so any notes you added there go too. A plain undo still keeps your memory.
