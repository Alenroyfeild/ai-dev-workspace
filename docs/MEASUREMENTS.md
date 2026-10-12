# Measurements

## Beta.4 Codex capture rerun (2026-10-12)

Candidate `756a412`, Codex `gpt-6-luna/high`, uses the same five rollout seeds as the prior 2/5 versus 5/5 run (seed base `978207194577267098`). Workspace **3/5**, Markdown-only **5/5**, baseline **0/5**; all 45 calls completed. Two workspace failures became passes and one prior pass failed. Small n and different kit revisions prevent a causal improvement claim. The rollout gate failed; PR #89 remains draft.

Codex→Codex decisions, n=3: workspace **3/3**, baseline **0/3**, all eight calls completed. Across both proofs: **5,191,712 input + 81,820 output tokens**; USD is unavailable, not zero. [Raw rollout](https://github.com/Alenroyfeild/ai-dev-workspace/blob/codex/beta4-capture-corrections/bench/results/2026-10-12-beta4-rollout-codex.json), [raw decisions](https://github.com/Alenroyfeild/ai-dev-workspace/blob/codex/beta4-capture-corrections/bench/results/2026-10-12-beta4-decisions-codex.json), [per-trial failures and prior comparison](https://github.com/Alenroyfeild/ai-dev-workspace/blob/codex/beta4-capture-corrections/bench/results/2026-10-12-beta4-rollout-codex.md).

All five prepared workspace Handoffs lack the latest lane and receipt. Successful trials recovered them from Next action. Trial 1 failed the lane check; trial 4 abstained despite both current values in its brief, alongside stale captured constraints. The next hypothesis is to persist the current correction from UserPromptSubmit before relying on a later transcript read, protecting it against stale Stop reads. This was not implemented or rerun. The earlier real full-transcript diagnostic already captured correctly; a tool-free turn-local replay, missing SessionEnd registration and Handoff replacement were concrete regressions, not the proven sole cause of every rollout failure.

Claude→Codex cross-check pending (Claude runs it). No Claude sessions were started for these proofs. The recorded 27 capture and seven brief-decision tests remain passing evidence for unchanged candidate code; proven scenarios were not repeated beyond the requested decisions proof.

## Claude and cross-assistant runs (2026-10-09)

`bench/run.py`, decisions scenario, Claude Code 2.1.278 `sonnet` for session 1, n=5 completions per arm, six hidden checks.

| Completion sessions | Baseline | Workspace | Results |
|---|---|---|---|
| Claude `sonnet` (kit 3484bde) | 0/5 | 5/5 | [json](../bench/results/2026-10-09-claude.json); mean cost $0.210 vs $0.257, time 114 vs 109 s |
| Codex `gpt-6-luna` (kit 3484bde) | 0/5 | 2/5 | [json](../bench/results/2026-10-09-claude-to-codex-3484bde.json); the brief cut decision 4 |
| Codex `gpt-6-luna` (kit ffce0bc, brief fix) | 0/5 | 5/5 | [json](../bench/results/2026-10-09-claude-to-codex.json); time 99 vs 88 s |

The first cross-assistant run found a real bug: Claude read the full task record over MCP, while Codex relied on the session-start brief, which showed too few words of the captured decisions. The fix keeps every numbered decision in the brief (tests/test_brief_decisions.py). Claude sessions keep their own saved transcripts on disk, as for a real user; in one smoke run a baseline recovered the decisions from them, in the five measured runs it did not. Small n, one synthetic task: this shows decisions crossing sessions and assistants, not general productivity.

## Public Codex continuity run (2026-10-07 UTC)

`python3 bench/run.py --provider codex -n 3`: gpt-6-luna/high, kit base 722bb89, 55-file decision fixture. One investigation per arm, followed by three fresh completion sessions from the same arm snapshot. Reference: 6/6 hidden checks; initial fixture: 2/6. Both arms use isolated temporary HOME/CODEX_HOME. The workspace retains memory; baseline does not. Prompts are identical, and hidden checks remain outside the worker fixture.

| Session 2 | Baseline | Workspace |
|---|---|---|
| All six checks / visible tests | 0/3 / 3/3 | 3/3 / 3/3 |
| Mean seconds | 64.5 | 106.5 |

This measures decision retention, not savings or statistical significance. Codex reports tokens but no USD price; cost is unknown, not zero. [Raw metrics and table](../bench/results/2026-10-07-codex.json), [reproducible method](../bench/README.md). Claude transport is unverified in this public runner; historical results below used the private harness.

Numbers here are measured, with the method, so you can judge them yourself. Small samples: read them as indications, not guarantees.

## Decisions made in conversation survive into the next session (2026-10-06)

**Question.** A developer tells the assistant product decisions in session 1, then a fresh session 2 is asked to "continue and finish". Does the work follow those decisions?

**Setup.**
- Synthetic Python repo, 55 files. `login('')` crashes. Visible tests only check "no crash".
- Session 1 prompt carries four decisions found nowhere in the code: empty or blank email returns `missing_email`; malformed returns `invalid_email`; `normalize()` and `recovery.py` must not change; every rejected login calls `audit.log_event("login_rejected", reason=...)`. Session 1 only investigates; code is reset afterwards so both arms start session 2 identically.
- Session 2 prompt, both arms: "Continue LOGIN-1 from the previous session and finish it."
- Claude Code 2.1.278, Sonnet, headless. Both arms isolated from personal settings, skills and MCP servers; the only difference is the workspace (AGENTS.md, hooks, skills, MCP server).
- Six hidden acceptance checks, one per decision plus the blank-email case. Unfixed code scores 2/6; a correct fix scores 6/6.

**Result (session 2, n=5 per arm).**

| | Without workspace | With workspace |
|---|---|---|
| All six decisions met | **0/5** | **5/5** |
| Mean hidden checks passed | 2.0/6 | 6.0/6 |
| Visible tests pass | 5/5 | 5/5 |
| Mean cost per session | $0.176 | $0.234 |
| Mean tool calls / wall time | 16.6 / 46 s | 18.4 / 55 s |

Without the workspace every run fixed the crash and passed the visible tests, but with the generic `invalid_email` and no audit event: work that looks done and is wrong. With it, every run followed all four decisions. The workspace session costs about $0.06 more; the baseline would need the developer to re-explain the decisions and redo the work.

**Automatic capture, no `/handoff` (2026-10-07).** Same setup, but session 1 got exactly the baseline prompt, with no instruction to save anything. The session-end hook captured the decisions from the transcript on its own. Session 2, n=5: all six decisions met in **5/5** runs, mean $0.251 per session (baseline 0/5, $0.176).

**What it took.** The first runs of this measurement exposed three bugs, all fixed before the result above: the session-start brief and `/pickup` told the model to ask instead of doing a given task, and a new session could not take over its own workspace's claim. The final runs used the fixed version.

**Also measured.** On an easy task whose failing tests point straight at the bug, the workspace gave no cost saving (mean $0.196 vs $0.189, n=3): when rediscovery is cheap, memory has little to save.
