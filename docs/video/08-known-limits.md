---
title: Known limits and boundaries
duration_hint: 45s
status: Stable
ws_version: 0.1.0b5
---
## Problem
Developers need clear transparency on what the workspace does not do, where heuristics apply, and verified boundaries.
## Steps
```sh
ws --version
ws audit
ws doctor
ws start --dry-run
```
## Guidance
Stable: System transparency, verified assistant coverage, and architectural boundaries per WORKER-PROTOCOL §8.
Key limits:
Benchmark: In controlled runs a plain Markdown handoff beat the workspace (5/5 and 4/5 vs 2/5 and 1/5 pass rate in the Oct 10 and Oct 11 Codex runs, n=5 each); the automatic-capture release gate is still unmet (see bench/README.md).
Local files, not a database: Memory lives as local Markdown files in `~/.ai-dev-workspace/<repo-name>`; no vector database, background AI daemon, or cloud sync.
Capture is best-effort: Transcript cue extraction is best-effort; explicit CLI commands (`ws remember`, `ws checkpoint`) are deterministic.
Guards are a safety net: PreToolUse guards block dangerous operations via pattern matching, but cannot interpret semantic intent or replace access permissions.
Client verification: Claude Code and Codex are live-tested on macOS and CI-tested on Linux/Windows; Cursor, Copilot, Gemini CLI, and Antigravity are fixture-tested.
## Narration
Reliable tooling depends on clear transparency about what works and where limits exist. `ai-dev-workspace` stores all task memory as plain Markdown files outside git, without background daemons or external vector databases. In controlled benchmark evaluations, a plain Markdown handoff outperformed the workspace's automatic brief in our latest Codex runs, so save important decisions explicitly. PreToolUse guards catch common destructive mistakes without acting as an unbypassable security perimeter. Running `ws audit` and `ws doctor` allows you to inspect your assistant configuration and review local findings at any time.
