---
name: pickup
description: Pick up a workspace task where the last session left off, from its saved next action.
---

Run `ws brief`. Use the user's task ID or the task named there; ask if the task is ambiguous.
Read only `ws task show <ID> --section "Next action" --section Blockers --section Evidence --section Handoff`. State the exact saved next action and blockers, with relevant evidence.
Do not reread the whole vault or change files. Continue implementation only when the user requests it.
