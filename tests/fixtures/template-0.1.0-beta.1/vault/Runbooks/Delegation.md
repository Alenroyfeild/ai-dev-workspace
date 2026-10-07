# Delegation: who does what

The lead assistant decides, plans, reviews and accepts. Cheaper workers do bounded work. Output from any worker is unverified until the lead checks it (open the file:line, re-run the test).

| Work | Cheapest capable worker |
|---|---|
| Decisions, plan approval, final review | lead assistant (planner tier, low effort) |
| Multi-file read-only exploration, evidence gathering | second provider in read-only mode (e.g. the `codex-worker` pack) |
| Implementation from an approved plan | worker tier (high effort) in the lead's tool |
| Big logs / JSON | `ws digest` (deterministic, free) |

Rules:
- Pass the worker the task's Objective, Next action, Blockers and the relevant evidence, never the whole vault.
- Log each step: `ws run log <task> <step> --provider <p> --model <m> --tokens-in N --tokens-out N --seconds S --result ok|failed|accepted|rejected`. `ws run report` shows where time and tokens go.
- If a worker is unavailable, say so; never silently switch providers.
