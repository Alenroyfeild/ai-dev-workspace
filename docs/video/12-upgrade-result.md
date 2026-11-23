---
title: Read the upgrade result
duration_hint: 45s
status: Preview
ws_version: 0.2.0
---
## Problem
After an upgrade you want to know exactly what changed, what was kept for review and how to roll back, not just that it ran.
## Steps
```sh
ws start --yes
ws upgrade --dry-run
ws upgrade --yes
ws start --undo
```
## Guidance
Preview (Experimental command, outside the 1.0 promise): after `ws upgrade --yes` applies changes, a "Migration result" block on stderr lists the CLI version, the template version, the repo wiring `kit_version`, files changed and kept, pending `.ws-new` proposals, the backup directory, the rollback text and an offline configuration check.
The block also says that running assistant sessions and MCP servers keep the old code until you start a new session or reload MCP connections. `ws doctor` flags a half-migrated store.
The dry run changes nothing and lists one line per proposed file.
Limits:
The configuration check is offline and checks that the config is valid, not that a live client is healthy.
Reloading running sessions is still your step.
## Narration
Zero point two makes the upgrade explain itself. The dry run lists every proposed file and changes nothing. Applying it prints a result block with the versions, the files changed or kept, any proposals waiting for review, where the backup went and how to roll back. It also reminds you that sessions already running keep the old code until you start a new one. Doctor flags a store that was only half migrated. These are experimental commands, so they may change.
