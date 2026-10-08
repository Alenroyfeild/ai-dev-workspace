# Cross-session continuity benchmark

Run `python3 bench/run.py --provider codex -n 3`. The default is n=5; choose `--model` explicitly to compare models. Claude transport is available with `--provider claude --allow-claude` but is unverified here. No software is installed. Sign in beforehand; unavailable providers stop without fallback.

Scenario data lives in `scenarios/`: fixture files, conversation-only decisions, session prompts and a reference solution. Hidden checks live in `checks/`, outside the worker's directory. Tests prove the initial decision fixture scores 2/6 and its reference fix scores 6/6 with visible tests passing. The 55-file synthetic fixture derives from the original golden run; it contains no customer data.

Each arm gets one investigation session, then n fresh completion sessions restored from its post-investigation snapshot at the same path. Code is reset between sessions; only the workspace arm retains task memory, project rules, hooks and skills. Both prompts are identical. Each model call has its own throwaway HOME/CODEX_HOME; Codex references the existing auth file via a temporary symlink and writes project trust only to that home. Personal config, skills, MCP and prior sessions are excluded. All writes target disposable fixtures. Hidden means undisclosed, not a filesystem read jail.

JSON results and a Markdown table go to `results/<UTC date>-<provider>.json`; use `--output` to keep private runs elsewhere. Records include transport completion, visible tests, individual hidden checks, tokens, tool calls and time. A success needs a completed provider call, passing visible tests and every hidden check. Codex does not return USD cost, so it is null; Claude result cost is retained when present. Export Codeburn locally for attribution, which can lag and is not a bill.

Budget: two setup calls plus 2*n completion calls. Historical Claude session-2 means of $0.176/$0.234 imply about $2.05 for n=5, plus setup; this is not a Codex price estimate. Small samples and a shared session-1 snapshot do not establish statistical significance or token savings. Measure continuity separately from latency and cost; report incomplete calls as inconclusive.

Add a JSON scenario and its Python checker; keep the checker and reference outside the worker fixture. Add a test proving the bad fixture fails the intended checks and the reference passes. Keep decisions absent from session-2 prompts and fixture code. The runner executes only after explicit invocation; normal tests make no model calls.
