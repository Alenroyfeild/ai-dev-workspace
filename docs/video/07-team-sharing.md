---
title: Team sharing (Preview)
duration_hint: 45s
status: Preview
ws_version: 0.1.0b5
---
## Problem
Developers on a team need to share approved decisions, domain knowledge, and lessons without central cloud tracking or automated leaks.
## Steps
```sh
ws start --yes
ws team init ../team-remote.git --attest-private --yes
ws remember "Wrap all JSON API responses in an envelope"
ws scope task:main team
ws share task:main --yes
ws sync --dry-run
ws team status
ws team unlink --yes
ws start --undo
```
## Guidance
Preview: Share vetted decisions, domain constraints, and lessons across a team via an explicit private Git repository.
Nothing is shared automatically: every shared item requires deliberate opt-in (`--team` or `ws share`), and `ws sync` previews all outbound files before pushing.
Limits:
Tested on local private repositories; hosted two-person remote verification is pending.
Requires manual Git syncing via `ws sync`; there is no central database, background sync daemon, or real-time multi-user editing.
Remote repositories must be strictly private; `--attest-private` requires developer confirmation before linking.
## Narration
Keeping team assistants aligned usually requires maintaining heavy documentation or trusting third-party cloud services. Team sharing in `ai-dev-workspace` synchronizes approved decisions through a private Git repository you control. Link your team repository using `ws team init` with private attestation. Decisions saved with the team flag generate local previews before inclusion in the team manifest. `ws sync` previews all outbound files before pushing, ensuring that private drafts remain strictly local to your machine.
