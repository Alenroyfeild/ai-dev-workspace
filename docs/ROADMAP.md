# Roadmap

The soft beta is shipped. Future work follows user feedback and measured runs; compatibility claims stay limited to what has been tested.

## Shipped in v0.1.0-beta.1

- [x] Tasks, claims, checkpoints, handoff and pickup, lessons, search, feedback, digests, run logs, validation and doctor checks.
- [x] Claude Code and Codex rules, MCP tools, skills and hooks, with automatic decision capture from Claude transcripts only.
- [x] Portable packs, workspace upgrades, `pipx` packaging and connections for Claude Code, Codex, Cursor, VS Code Copilot and Gemini CLI.
- [x] Codebase maps, existing Graphify report links, toolbox profiles, tool-load estimates and permission-based assist suggestions.
- [x] Role routing and bounded read-only delegation with a sandbox self-test.
- [x] Measured session-memory results with method and limitations published in [MEASUREMENTS.md](MEASUREMENTS.md).

## Next

- [ ] Test documented Cursor, Copilot and Gemini CLI connections in real client sessions.
- [ ] Extend automatic decision capture beyond Claude when another client exposes a suitable transcript or equivalent.
- [ ] Prepare the public v0.2 launch based on beta feedback and test results.

## Later, only with evidence

- [ ] Consider a write-capable second-AI worker only inside a disposable worktree and outer container, after the hostile self-test passes.
- [ ] Add analytics or vector search only if the current run log or search fails real user needs.

## Not planned

- A hosted service, database or scheduler. The workspace remains files and small tools.
