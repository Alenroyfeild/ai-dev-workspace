---
name: thinkbeforeact
description: Plan requested code changes with checks for need, reuse, risk and verification.
argument-hint: <what you want changed or built>
---

## Output style: terse — ON by default for this run
Every chat line in this run follows these rules (files you write stay normal prose).
- Drop articles, filler, pleasantries, hedging. Fragments OK. One idea per sentence, 20 words max, active voice.
- Keep exact: file:line, code, commands, API names, error strings, numbers. Never drop not/never/no/only.
- No invented abbreviations, arrows, decorative tables or emoji, tool-call narration or recap.
- Pattern: `[thing] [action] [reason]. [next step].`
- Plain sentences for security warnings, irreversible actions, or when terse order could be misread.
- User says "normal mode" → plain style.

## Steps (do not edit code in this skill)
$ARGUMENTS

0. If a `workspace.json` exists here or above: `ws task find <ticket-or-branch>` and read only that record's Next action, Blockers, Handoff (MCP: `find_task`, `read_task` with `sections`). `ws lesson search "<topic words>"` and `ws search "<topic words>"` before reading code.
1. **Needed here?** Prove it with file:line, callers, current behavior. Another platform's behavior is not proof.
2. **What could break?** List every working flow through the code. If one could change, keep the old path and gate the new one (feature flag, remote config or version check).
3. **Approach:** reuse as-is / small change / rework / build new, with the reason. Prefer reuse; model state explicitly (enum/state machine) where it matters.
4. **Plan** if more than one step: numbered, a verification per step, who does each step (cheapest capable worker; the lead assistant decides and reviews).
5. **Drawbacks and unverified points.** Unverified is a valid answer.
6. Record findings and plan: `ws checkpoint <ID> --status ready --next "<first plan step>" --note "Findings=..."`. New lesson: `ws lesson add "what happened → rule"`. Then stop for the user's go-ahead.
