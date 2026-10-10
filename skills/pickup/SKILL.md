---
name: pickup
description: Show where a workspace task stands (saved next action, blockers, evidence) when the user asks to resume or asks for status without giving a concrete task.
---

If a "Saved task memory" brief is already in context, do not run `ws brief` again; treat its Next action and Blockers as already read, and request only missing sections such as Evidence or Handoff. Otherwise run `ws brief`, then read `Next action`, `Blockers` and `Handoff` by default: `ws task show <ID> --section "Next action" --section Blockers --section Handoff`, or call MCP `read_task` (which selects those sections by default). Request the full record only when needed: omit `--section` for `ws task show`, or pass `sections: []` to MCP `read_task`. Do not reread the whole vault.
If the user asked you to continue or finish the task, go on and do the saved next action. Otherwise state the next action, blockers and relevant evidence, and ask whether to continue.
