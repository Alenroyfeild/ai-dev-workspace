# Cross-session continuity benchmark

## Corrected rollout: independent paired investigations

Current [2026-10-10 R9-B1 n=5 run](results/2026-10-10-R9-B1-rollout-codex.json), unmodified dev `cbe3f68`, Codex CLI 0.155.1, `gpt-6-luna`/high:

| Arm | Pass | Abstention | Guess or incomplete | Inconclusive | Mean wall seconds | Reported input / output tokens |
|---|---|---|---|---|---|---|
| Fresh baseline | 0/5 | 3/5 | 2/5 | 0/5 | 115.9 | 1,065,083 / 14,279 |
| Workspace | 1/5 | 1/5 | 2/5 | 1/5 | 189.7 | 1,642,628 / 28,863 |
| Markdown handoff | 4/5 | 0/5 | 0/5 | 1/5 | 66.4 | 851,497 / 10,950 |

All 15 scheduled arms remain in the denominator. There were 41 worker invocations; the final workspace and Markdown investigations exited 1, leaving their correction/completion calls unattempted. Failed-turn usage is unavailable, so these are reported tokens, not complete billable totals. Codeburn did not price Luna; USD is unpriced, not zero. No failed arm was rerun or replaced. Fixed order, small n and incomplete attempts preclude speed or savings claims.

[Retained synthetic memory](results/2026-10-10-R9-B1-rollout-codex.memory.jsonl) shows stale initial Captured values in the completed workspace seeds. The one workspace pass saved the correction in `Next action`; it does not prove automatic correction capture. Local observation recorded no correction capture update between the investigation and fresh completion. The precise lifecycle/transport cause remains unverified; the runner does not retain error details. A documented SessionEnd capture callback is a candidate, not a proven fix. This run establishes neither superiority over Markdown nor a passed automatic-capture release gate. The batch stopped after two consecutive worker transport failures; a tested capture fix and rerun remain pending. No Claude sessions.

Follow-up diagnosis: Astra's `full_checkpoint` reproduction confirms a rendering regression: the 198-word brief drops `missing_email` and `invalid_email`, although both remain captured in the task. That supports fixing the section budgets. It does **not** establish truncation as the sole cause of this rollout result: none of the saved final workspace Handoffs contain the superseding lane/receipt, and the pre-completion seed-3 observation places them in `Next action`, not Captured text. Completion briefs were not recorded verbatim, so their exact contents cannot be claimed from final snapshots; seeds 0 and 2 lack a complete pre-completion observation. The observed seed-3 next action is short enough to fit its current section budget. The earlier pre-#77 4/5 run and this 1/5 run used different seeds and are not a controlled causal comparison. Both the missing capture update and the reproduced rendering loss require separate verification.


Run `python3 -m bench.rollout_run -n 5 --output /tmp/rollout.json`. This POSIX runner uses installed Codex `gpt-6-luna`/high, without installs. Each of five independent seeds gets a two-turn investigation in each arm: observe one rejected preparation retry, then receive a superseding lane and replacement opaque approval receipt. The correction requests a read to exercise worked-session capture. A fresh completion receives no conversation facts except the arm's retained memory: baseline retains none, workspace uses task memory/hooks/skills, and the control writes plain `HANDOFF.md`.

Optional `--provider claude` uses Sonnet, a throwaway HOME/config directory, project-only hooks, strict MCP, confined file reads and a required Bash sandbox with no unsandboxed retry. It requires Claude Code >= 2.1.285 and already available sandbox dependencies; it never installs them or falls back to the real HOME. Authentication must work in that isolated environment (for example an explicitly supplied API key, withheld from sandboxed commands); unavailable authentication or sandboxing cannot count as a successful trial. Session/resume arguments, result parsing, version rejection and interruption cleanup are fixture-tested; live Claude authentication, isolation and benchmark outcomes remain **unverified**. This adapter does not change the historical `bench/run.py` Claude transport or its measured results below. Controls follow the official [sandbox documentation](https://code.claude.com/docs/en/sandboxing), [settings precedence](https://code.claude.com/docs/en/settings), and [CLI tool restrictions](https://code.claude.com/docs/en/cli-reference).

Listed fixture code, artifacts, visible tests and their file mtimes match at completion start; commit dates are fixed. Expected values stay in the parent. Preparation appends to the in-fixture `.step-log`; the harness checks it for another attempt and checks file replacement. This log is **not tamper-proof**: a worker can truncate or edit it. It measures cooperative continuity, not adversarial enforcement. No checker files or transcript paths enter the worker fixture. Partial results are saved after every arm; the answer-generating seed is published after all workers finish. This is not a filesystem/process-memory security jail.

Measured [2026-10-09, independent n=5](results/2026-10-09-rollout-codex.json), kit `190d68c`, step-log fixture:

| Arm | Pass | Abstention | Guess or incomplete | Inconclusive setup/transport | Mean full wall seconds | Full input / output tokens |
|---|---|---|---|---|---|---|
| Fresh baseline | 0/5 | 2/5 | 3/5 | 0/5 | 121.8 | 887,824 / 12,419 |
| Workspace | 2/5 | 1/5 | 1/5 | 1/5 | 201.4 | 1,887,577 / 31,310 |
| Markdown handoff | 3/5 | 0/5 | 2/5 | 0/5 | 131.9 | 989,471 / 13,396 |

All outcomes are retained. Inconclusive setup is counted in the five seeds, not as a completion success. Full usage and wall time include both investigation turns and any completion. No cost advantage is established. Codeburn did not price Luna records, so USD is unpriced, not zero. The append-only log is cooperative and **not tamper-proof**. Capture success does not guarantee every resumed correction is recalled. No live Claude or other third-party clients were run.

Historical run (different fixture and capture snapshot):

Measured [2026-10-08, n=5](results/2026-10-08-rollout-codex.json):

| Arm | Exact lane + receipt, no retry, unchanged behavior | Clarification / abstention | Mean setup / completion seconds | Mean full wall seconds | Full input / output tokens |
|---|---|---|---|---|---|
| Fresh baseline | 0/5 | 5/5 | 24.7 / 36.2 | 62.6 | 903,017 / 13,305 |
| Workspace | 5/5 | 0/5 | 66.9 / 52.2 | 121.9 | 2,117,315 / 35,773 |
| Markdown handoff | 4/5 | 1/5 | 31.4 / 23.7 | 56.8 | 1,027,766 / 13,694 |

All 15 measured completion calls passed visible tests, preserved listed unrelated code, and recorded no retries in the original cooperative FIFO audit; no guesses or transport failures. That audit could be drained by a worker, so it does not prove adversarial no-retry safety. Usage includes both investigation turns plus completion, with cumulative resume counters differenced. Codeburn returned zero-priced Luna records: dollar cost is **unpriced**, not free. Full wall time includes setup and local accounting. These 45 model calls demonstrate narrow retention, not coding superiority, statistical significance or savings; workspace was slower and used more tokens. Plain Markdown worked well here.

Measurement used the disposable capture snapshot listed in JSON (`dce68bd`, assembled from `283b362`, `ecba456`, `c6b9755`) plus runner `924ea97`. Subsequent review improved late-clause capture, conflict labels, diagnostic failure handling, fixture integrity, trusted-test isolation and harness error cases; the separate current n=5 run above records their actual outcomes. An aborted preliminary protocol omitted a read in the correction turn and missed workspace corrections; it is excluded from these counts. Reference/negative controls and interrupted-result persistence are tested without model calls. Older snapshot-based ceiling measurements remain below as historical evidence.

Run `python3 bench/run.py --provider codex -n 3`. The default is n=5; choose `--model` explicitly to compare models. Claude transport is available with `--provider claude --allow-claude` but is unverified here. No software is installed. Sign in beforehand; unavailable providers stop without fallback.

Scenario data lives in `scenarios/`: fixture files, conversation-only decisions, session prompts and a reference solution. Hidden checks live in `checks/`, outside the worker's directory. Tests prove the initial decision fixture scores 2/6 and its reference fix scores 6/6 with visible tests passing. The 55-file synthetic fixture derives from the original golden run; it contains no customer data.

Each arm gets one investigation session, then n fresh completion sessions restored from its post-investigation snapshot at the same path. Investigation-only scenarios reset code; `preserve_code` retains completed work for the interruption scenario, whose `setup` receipts must match before trials start. Only the workspace arm retains task memory, project rules, hooks and skills. Both arms receive identical prompts. Each model call has its own throwaway HOME/CODEX_HOME; Codex references the existing auth file via a temporary symlink and writes project trust only to that home. Personal config, skills, MCP and prior sessions are excluded. All writes target disposable fixtures. Hidden means undisclosed, not a filesystem read jail.

Scenario 2: `--scenario lessons`. Session 1 learns that rebuilding invalidates a cached consumer receipt; session 2 must publish without repeating that failed approach. Hidden checks test the receipt, absence of a rebuild invocation, rows and unchanged builders/tests. Scenario 3: `--scenario resume`. Session 1 prepares once and stops; session 2 must publish the prepared receipt without repeating preparation. Hidden checks inspect the append-only step log, prepared artifact, release and unchanged pipeline/tests. Visible tests check only rows; references pass every check, and tests demonstrate that repeating either forbidden command fails a hidden check.

Measured 2026-10-09, Claude Code 2.1.278 `sonnet`, decisions scenario, kit 3484bde, n=5: baseline 0/5, workspace 5/5 ([results](results/2026-10-09-claude.json)); mean completion-session cost $0.210 vs $0.257, mean time 114 vs 109 seconds. Claude sessions keep the real HOME so sign-in works; their isolation is project-only settings and strict MCP, so Claude's own saved transcripts stay on disk as they would for a real user. In a one-run smoke test a baseline session found and read the previous session's transcript under `~/.claude/projects/` and passed; in the five measured runs it did not. Native transcript recovery exists but was not reliable here.

Measured 2026-10-08, Codex `gpt-6-luna`/high, n=3: both arms passed 3/3 in [lessons](results/2026-10-08-lessons-codex.json) and [resume](results/2026-10-08-resume-codex.json). Mean completion times were baseline/workspace 43.9/48.2 seconds (lessons) and 41.0/44.8 seconds (resume). These small fixtures have a ceiling effect: a fresh baseline can infer the safe action from repository artifacts. They prove the checks and fresh-session workflow run, not a workspace advantage or savings. The step logs are observable receipts, not tamper-proof audit storage.

JSON results and a Markdown table go to `results/<UTC date>-<provider>.json`; use `--output` to keep private runs elsewhere. Records include transport completion, visible tests, individual hidden checks, tokens, tool calls and time. A success needs a completed provider call, passing visible tests and every hidden check. Codex does not return USD cost, so it is null; Claude result cost is retained when present. Export Codeburn locally for attribution, which can lag and is not a bill.

Budget: two setup calls plus 2*n completion calls. Historical Claude session-2 means of $0.176/$0.234 imply about $2.05 for n=5, plus setup; this is not a Codex price estimate. Small samples and a shared session-1 snapshot do not establish statistical significance or token savings. Measure continuity separately from latency and cost; report incomplete calls as inconclusive.

Add a JSON scenario and its Python checker; keep the checker and reference outside the worker fixture. Add a test proving the bad fixture fails the intended checks and the reference passes. Keep decisions absent from session-2 prompts and fixture code. The runner executes only after explicit invocation; normal tests make no model calls.
