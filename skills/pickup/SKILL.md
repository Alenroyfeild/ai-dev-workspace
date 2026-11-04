---
name: pickup
description: Show where a workspace task stands (saved next action, blockers, evidence) when the user asks to resume or asks for status without giving a concrete task.
compatibility: Requires ws on PATH (pipx install ai-dev-workspace --pip-args='--pre') and a Git repository initialized with ws start.
---

If a "Saved task memory" brief is already in context, do not run `ws brief` again; treat its Next action and Blockers as already read, and request only missing sections such as Evidence or Handoff. Otherwise run `ws brief`, then read `Next action`, `Blockers` and `Handoff` by default: `ws task show <ID> --section "Next action" --section Blockers --section Handoff`, or call MCP `read_task` (which selects those sections by default). Request the full record only when needed: omit `--section` for `ws task show`, or pass `sections: []` to MCP `read_task`. Do not reread the whole vault.

Before continuing, compare the repository and environment state against the saved handoff to check for drift:
- compare the current branch and working tree (`git status -sb`) with the saved handoff
- verify whether uncommitted work or unpushed commits have changed
- check whether failing checks or broken tests noted in the handoff have been resolved or new failures appeared
If the branch changed, uncommitted work drifted, or test status differs from the saved Evidence, flag the drift to the user before resuming.

If the user asked you to continue or finish the task, go on and do the saved next action (noting any detected drift first). Otherwise state the next action, blockers, relevant evidence, and any detected drift, and ask whether to continue.
