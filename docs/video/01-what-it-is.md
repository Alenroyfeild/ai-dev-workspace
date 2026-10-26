---
title: Shared task memory
duration_hint: 30s
status: Stable
ws_version: 0.1.0b5
---
## Problem
Changing assistants can lose the decisions and next step for a task.
## Steps
```sh
ws --version
ws demo
```
## Guidance
Stable: explicit shared Markdown memory in released beta.5. This offline demo
saves a decision and reads it in a fresh process; it starts no assistant.
It demonstrates storage, not a live Claude-to-Codex session or a performance gain.
