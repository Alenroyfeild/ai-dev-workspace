# Changelog

## 0.1.0-beta.1 – unreleased
- First version: core CLI, MCP server, task/claim/checkpoint, search, lessons, feedback, digest, run log, doctor.
- Packs: obsidian, local-llm, codex-worker (read-only, with hostile self-test), ios.
- Skill: thinkbeforeact.
- Release loop: `ws version`, `ws update [--check]`, feedback → GitHub issue (`ws feedback submit/link/sync`), tag-driven release workflow.
- `ws notices` / MCP `notices`: the assistant suggests updates, fixed issues and unshared feedback at session start (daily cache, `WS_OFFLINE=1` to disable).
