---
name: thinkbeforeact
description: Plan requested code changes with checks for need, risk, outward effects and verified evidence.
compatibility: Requires ws on PATH (pipx install ai-dev-workspace --pip-args='--pre') and a Git repository initialized with ws start.
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
1. **Needed here?** Prove it with file:line, callers, current behavior. Another platform's behavior is not proof. Label every claim verified (a command you ran, with its output), inferred or unknown, with its source.
2. **What could break?** List every working flow through the code; for a shared entry point, search every call site and list each. If one could change, keep the old path and gate the new one (feature flag, remote config or version check).
3. **Bug or failure: root cause first.** Read the exact error, reproduce it, check what changed and earlier runs, and compare with a similar path that works. Write one hypothesis and test it with the smallest change. Never explain a failure from memory. Two failed fixes for one symptom: stop and rethink the mechanism with the user.
4. **Approach:** reuse as-is / small change / rework / build new, with the reason. Prefer reuse; model state explicitly (enum/state machine) where it matters.
5. **Plan** if more than one step: numbered, a verification per step, who does each step (cheapest capable worker; the lead assistant decides and reviews).
6. **Drawbacks and unverified points.** Unverified is a valid answer.
7. Record findings and plan: `ws checkpoint <ID> --status ready --next "<first plan step>" --note "Findings=..."`. New lesson: `ws lesson add "what happened → rule"`. Then stop for the user's go-ahead.

## Concerns: check each that applies
- **Outward effects:** before re-running, merging or dispatching anything that starts CI, a deploy or a hook, read its code and name what it sends outward (uploads, messages, pushes, state on shared runners) with file:line.
- **Checks and guards:** capture a command's output before filtering it; run the failure path (stub the command to fail) as well as the pass path.
- **Reviews and hunts:** probe adversarially (bypass, negative and boundary inputs) and save each probe's command, input and output. Re-confirming tested behavior is not a hunt.
- **Missing file or instruction:** don't block and don't invent a replacement; follow the project's AGENTS.md and say what is missing.
- **Outside things:** downloads, installs, paid model calls, new services and third-party code need the owner's yes; check the license before reusing code or text.
- **Big input** (log, JSON or diff over about 100 lines): `ws digest <file>` first, then confirm single values in the original.
- **One ask per item:** record an open question once (task record or ledger) instead of repeating it.

## Verification gate
Before saying "works", "fixed" or "passes": name the command that proves it, run it fresh, read its output and exit code, then claim it with that evidence. Otherwise state the real status ("not run", "tests only", "worker said done, not checked").
