---
name: lesson
description: Record a requested mistake-to-rule lesson in workspace memory.
---

Use the user's requested lesson and verified session context to form one line: what happened → rule. Ask if either part is missing; omit secrets and private identifiers.
When verified context identifies relevant files or an area, suggest optional `--path "<relative repo glob>"` (repeatable) and `--area "<area>"` tags; do not guess paths. Run `ws lesson add "<what happened → rule>"` with the agreed tags, then `ws lesson search "<distinctive words>"` to confirm it was recorded. Report the saved rule briefly. Briefs prefer lessons matching files changed from the claimed task's starting commit, then its title/area.
