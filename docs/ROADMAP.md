# Roadmap

Improvements are driven by recorded feedback (`ws feedback`, GitHub issues) and measured runs (`ws run report`), one at a time.

## Now (0.1)
- [x] Core: tasks, claims, checkpoints, search, lessons, feedback, digest, run log, validate, doctor
- [x] MCP server (stdio), verified with Claude Code's `mcp list`
- [x] Pluggable packs: obsidian, local-llm, codex-worker (read-only), ios
- [x] Think-before-act skill

## Next
- [ ] **Golden run**: one real task end to end (lead plans, worker explores, lead implements and reviews), logged with `ws run log`, compared against the same task without the workspace. Publishes the first measured token/time numbers.
- [ ] `pipx install` packaging with the kit data included.
- [ ] `ws init` interactive mode: ask domain, repos and optional packs.
- [ ] Automatic token capture where the assistant exposes usage, instead of manual `--tokens-in`.
- [ ] More domain packs: android, web, backend (contributions welcome).
- [ ] Feedback triage: `ws feedback` export to GitHub issues.

## Later (only with evidence it is needed)
- [ ] **Write-capable second-AI worker**, inside a disposable git worktree and an outer container (e.g. Apple `container`), released only after the same hostile self-test passes. Host-level sandboxes alone failed this test in our evaluation: shell writes escaped a workspace-write sandbox.
- [ ] Agent-flow analytics beyond `ws run report` (e.g. an evaluation framework) if the JSONL log stops being enough.
- [ ] Optional vector search if `ws search` misses too much on large vaults.

## Not planned
- A hosted service, a database or a scheduler. The workspace stays files + small tools.
