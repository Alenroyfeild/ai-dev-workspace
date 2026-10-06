---
name: handoff
description: Save verified task progress and an exact next action.
---

Use the user's task ID, or `ws brief`; ask if the task is still ambiguous. Read `ws task show <ID> --section "Next action" --section Evidence --section Blockers`.
From the current session's verified work, run `ws checkpoint <ID> --status <current-status> --next "<exact unfinished step>" --note "Evidence=<facts and checks>" --note "Blockers=<blockers or None>"`. Preserve still-relevant evidence; never invent checks or include secrets/private identifiers.
Read back those sections with `ws task show` and state the saved next action. This saves workspace memory only; do not commit or push.
