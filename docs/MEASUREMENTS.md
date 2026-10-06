# Measurements

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

**What it took.** The first runs of this measurement exposed three bugs, all fixed before the result above: the session-start brief and `/pickup` told the model to ask instead of doing a given task, and a new session could not take over its own workspace's claim. The final runs used the fixed version.

**Also measured.** On an easy task whose failing tests point straight at the bug, the workspace gave no cost saving (mean $0.196 vs $0.189, n=3): when rediscovery is cheap, memory has little to save.
