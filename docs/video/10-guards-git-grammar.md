---
title: Guards that read git's grammar
duration_hint: 45s
status: Stable
ws_version: 0.1.0b7
---
## Problem
Git accepts shortened option names and attached option values, so a guard that only matches exact spellings can miss a remote deletion or deny a harmless push.
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
Stable: In 0.1.0b7 the opt-in `guards` pack parses `git push` the way git does. Examples below were checked with `guards.command_reason` in a clone; nothing was executed against a remote.
Denied, with the real reason "This remote branch will be deleted for everyone.": `git push origin --delete main`, the abbreviation `git push origin --del main`, `git push origin --prune`, `git push --mirror origin`, the abbreviation `git push --mirr origin`, and `git push origin :main`.
Allowed, with an empty reason: `git push origin main`, `git push -o ci.skip origin main`, `git push --push-option=ci.skip origin main`, and `git push --dry-run --prune origin`.
These examples are an illustration of the parser, not a recording of a live assistant session.
Limits:
Guards are a safety net for common mistakes, not an unbypassable security boundary.
Pattern parsing cannot interpret intent or every obfuscated shell form; normal permissions and review stay required.
Temporarily bypass guards for one session with `WS_GUARDS=off`.
## Narration
Git lets you shorten options and attach values, so an exact-match guard can be sidestepped by accident. Beta seven teaches the guards pack git's grammar. Deleting a remote branch with delete, with the shortened del, with prune, with mirror, or with a colon refspec is denied. Ordinary pushes, pushes with a push option, and dry runs are allowed. These outputs come from the real checker, not a live session. Guards remain a safety net for common mistakes, not a security boundary, so keep your normal permissions and review.
