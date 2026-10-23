---
title: Preview, connect, undo
duration_hint: 45s
status: Stable
ws_version: 0.1.0b5
---
## Problem
Set up memory from your code repo, with a chance to inspect the changes first.
## Steps
```sh
ws --version
ws start --dry-run
ws start --yes
ws start --undo
```
## Guidance
Stable: preview lists local files; --yes applies without prompting.
Undo removes unchanged wiring and keeps private memory outside the repo.
Existing Codex config may still need a manual paste. This is setup, not client proof.
