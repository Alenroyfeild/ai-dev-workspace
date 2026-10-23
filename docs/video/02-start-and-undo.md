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
Before recording, the maintainer supplies an isolated released-package venv:
`python3 -m venv /tmp/video-venv`, then
`/tmp/video-venv/bin/python -m pip install ai-dev-workspace==0.1.0b5`.
The renderer never installs anything. Use `--ws-python /tmp/video-venv/bin/python`.
Stable: preview lists local files; --yes applies without prompting.
Undo removes unchanged wiring and keeps private memory outside the repo.
Existing Codex config may still need a manual paste. This is setup, not client proof.
