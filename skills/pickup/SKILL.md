---
name: pickup
description: Show where a workspace task stands (saved next action, blockers, evidence) when the user asks to resume or asks for status without giving a concrete task.
---

If a "Saved task memory" brief is already in context, do not run `ws brief` again. Otherwise run `ws brief`. Use the user's task ID or the task named there; ask if it is ambiguous.
Read only the sections still missing: `ws task show <ID> --section Evidence --section Handoff` (add "Next action" and Blockers if no brief was shown). Do not reread the whole vault.
If the user asked you to continue or finish the task, go on and do the saved next action. Otherwise state the next action, blockers and relevant evidence, and ask whether to continue.
