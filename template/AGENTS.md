# Workspace rules (all AI assistants)

This folder is the shared memory for AI-assisted work on the code checkouts listed in `workspace.json`. Read only what the current step needs; never ingest the whole vault or repo.

## Start of a session
1. Find the task: `ws task find <ticket-or-branch>` (MCP: `find_task`). Read only that record's Next action, Blockers and Handoff first. No record: `ws task new <ID> "<title>"`.
2. Claim it before changing anything: `ws claim <ID>`. A claim made earlier in this workspace is resumed; a claim by another machine or person means stop and ask. One writer per checkout.
3. Offer `ws notices` suggestions once; apply only after a yes. Nothing to report: say nothing.
   Suggest missing recommended tools once; install only after the user says yes.
4. Look things up instead of re-discovering them: `ws search "<words>"` (product, project, runbooks, past analysis) and `ws lesson search "<words>"`.

## While working
- Before changing code, think before act: is it needed, what working flows could break (gate them with a flag or version check), can existing code be reused, a numbered plan with a check per step, and proof instead of claims. Claude: `/thinkbeforeact`.
- Big logs or JSON: `ws digest <file>` and read the summary, not the file.
- Delegate cheap work to cheaper workers when it saves tokens; the lead assistant decides and reviews. Log each delegated step: `ws run log <ID> <step> --provider <name> ...`.
- Never commit or push unless the user asks in that turn. Never discard the user's edits.

## Before stopping
- `ws checkpoint <ID> --status <status> --next "<exact next action>"`. Another assistant must be able to continue from the record alone.
- A mistake or a useful lesson: `ws lesson add "what happened → rule"`. When the user is annoyed by the workspace, a `ws` command fails, or they suggest an improvement, offer to record it: `ws feedback add "..." --kind idea|bug|friction|praise` (only with their yes; never include company or customer details). Sharing it with the maintainers happens later via the feedback notice.
