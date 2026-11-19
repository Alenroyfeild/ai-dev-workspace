---
title: Check before you update
duration_hint: 45s
status: Preview
ws_version: 0.2.0
---
## Problem
Updating the tool that holds your memory should not surprise you with a pulled branch or a changed checkout.
## Steps
```sh
ws start --yes
ws update --check
ws start --undo
```
## Guidance
Preview (Experimental command, outside the 1.0 promise): `ws update --check` reports the installation type, the local Git state and the manual choices you still have, without pulling or changing branches.
With `WS_OFFLINE=1` the check skips the network and uses local refs only, and it says so in its first lines. A package install is told to run `pipx upgrade ai-dev-workspace` itself; `ws update` never runs pipx for you.
To upgrade from beta.7, run `ws update`, then `ws upgrade --dry-run`, then `ws upgrade --yes`, then `ws start` in each repo.
Limits:
The check reports; it does not decide for you, and it does not prove the update is safe for your own edits.
Running assistant sessions and MCP servers keep the old code until you start a new session or reload.
## Narration
Before you update, ask what would happen. Zero point two adds a check that reads the installation type and the local Git state and lists the choices that stay yours, without pulling or switching a branch. Offline, it uses only local references and says so. When you are ready, update, preview the workspace upgrade, apply it, and run start again in each repo. This is an experimental command, so it may change before one point zero.
