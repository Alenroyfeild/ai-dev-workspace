# Client verification

Checked 2026-10-09 against the official documentation of each client. Only documentation was read; no client was installed or run, so "matches" means the generated config and hook output agree with the docs, not that a live session was exercised. Pinned by `tests/test_client_docs.py`.

Status: **matches** (code agrees with docs), **fixed**, **unclear** (docs silent or contradictory; code left as is).

| Item | Our behaviour | Official doc says (URL) | Status |
|---|---|---|---|
| Cursor rule file | `.cursor/rules/ws-current-task.mdc`, front matter `description` + `alwaysApply: true` (no `globs`) | Project rules live in `.cursor/rules` as `.mdc` with `description`, `globs`, `alwaysApply`; `alwaysApply: true` ignores the other two (https://cursor.com/docs/context/rules) | matches |
| Cursor hooks file and shape | `.cursor/hooks.json`, `"version": 1`, flat entries `{type, command, timeout}` per event | Project file `.cursor/hooks.json`; `version` required, use `1`; entries are `{command, type, timeout...}` (https://cursor.com/docs/hooks) | matches |
| Cursor events | `sessionStart`, `preCompact`, `stop`, `sessionEnd`, `beforeSubmitPrompt` | All five are listed events (https://cursor.com/docs/hooks) | matches |
| Cursor timeout | `10` | Seconds (https://cursor.com/docs/hooks) | matches |
| Cursor transcript input | reads `transcript_path` | Common input field on every hook; `null` when transcripts are disabled (https://cursor.com/docs/hooks) | matches |
| Cursor sessionStart context | `{"additional_context": ...}` | `sessionStart` output accepts `additional_context` (string) and `env`; fire-and-forget (https://cursor.com/docs/hooks) | matches |
| Cursor prompt guard | `{"continue": false, "user_message": ...}` | `beforeSubmitPrompt` output `continue` / `user_message` (https://cursor.com/docs/hooks) | matches |
| Gemini settings path and MCP | `.gemini/settings.json`, `mcpServers` | Project `.gemini/settings.json`; `mcpServers.<name>` with `command`/`args` (https://geminicli.com/docs/reference/configuration/) | matches |
| Gemini hook events and nesting | `SessionStart`, `PreCompress`, `AfterAgent`, `SessionEnd`, `BeforeAgent`; event -> `[{hooks:[{type,command,timeout}]}]` | Same event names and nesting (https://geminicli.com/docs/hooks/reference/) | matches |
| Gemini timeout | `10000` | Milliseconds, default 60000 (https://geminicli.com/docs/hooks/reference/) | matches |
| Gemini SessionStart output | `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}` | `hookSpecificOutput.additionalContext` (https://geminicli.com/docs/hooks/reference/) | matches |
| Gemini prompt guard | `{"decision": "deny", "reason": ...}` | `BeforeAgent` `decision: "deny"` blocks the turn, `reason` required (https://geminicli.com/docs/hooks/reference/) | matches |
| Gemini memory store (`ws import native`) | Reads `## Gemini Added Memories` in `~/.gemini/GEMINI.md` | The memory tool page now says the agent edits Markdown files directly: repo `GEMINI.md`, a private per-project memory folder, or global `~/.gemini/GEMINI.md`; `/memory` documents only `show`, `refresh`/`reload`, `list`, no `add` (https://geminicli.com/docs/tools/memory, https://geminicli.com/docs/reference/commands). The upstream `memoryTool.ts` on `main` no longer contains the section heading; per-project dir is `~/.gemini/tmp/<project-id>/memory` (https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/config/storage.ts) | unclear: kept the reader for files written by older versions; format of the new per-project memory is undocumented. Wording in `docs/COMMANDS.md` updated |
| Copilot instructions | `.github/copilot-instructions.md` | Repository-wide instructions file; `AGENTS.md` also supported (https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions) | matches |
| VS Code MCP | `.vscode/mcp.json`, top-level `servers` | Top-level `servers` object (https://code.visualstudio.com/docs/copilot/customization/mcp-servers) | matches |
| VS Code hook file and shape | `.github/hooks/ai-dev-workspace.json`, flat `{type, command, timeout}` entries | Workspace hooks in `.github/hooks/*.json`; flat entries (https://code.visualstudio.com/docs/agent-customization/hooks) | matches |
| VS Code events, timeout | `SessionStart`, `PreCompact`, `Stop`; timeout `10` | Same PascalCase events; `timeout` in seconds, default 30 (https://code.visualstudio.com/docs/agents/reference/hooks-reference) | matches |
| VS Code SessionStart output | `hookSpecificOutput.additionalContext` | Same, with `hookEventName: "SessionStart"` (hooks reference above) | matches |
| VS Code Stop output | We never block on Stop (capture only) | Stop blocking is `decision: "block"` nested under `hookSpecificOutput`, not top-level. Irrelevant today because we emit `{}`; remember it if a VS Code Stop nudge is added | matches (note) |
| Claude Code SessionStart | `hookSpecificOutput.additionalContext` (plain stdout also accepted) | Same, plus optional `sessionTitle` (https://code.claude.com/docs/en/hooks) | matches |
| Claude Code Stop | `{"decision": "block", "reason": ...}` once, skipped when `stop_hook_active` | `decision: "block"` + `reason`; `stop_hook_active` input; cap of 8 continuations (https://code.claude.com/docs/en/hooks) | matches |
| Claude Code UserPromptSubmit | Prompt guard exits 2 with reason on stderr | Exit 2 blocks the prompt; `decision: "block"` also accepted (https://code.claude.com/docs/en/hooks) | matches |
| `CLAUDE_CODE_TASK_LIST_ID` | Not used (report only) | Documented: shares a task list across sessions, stored under `~/.claude/tasks/<id>/` (https://code.claude.com/docs/en/env-vars, https://code.claude.com/docs/en/interactive-mode) | documented, not implemented |
| Codex hooks | `.codex/hooks.json`, `SessionStart`, `PreCompact`, `Stop`, `UserPromptSubmit`; nested `{hooks:[{type,command,timeout}]}`, timeout `10` | Project `<repo>/.codex/hooks.json` (loaded when `.codex/` is trusted); same events and nesting; seconds; `/hooks` review and trust (https://learn.chatgpt.com/docs/hooks, redirected from https://developers.openai.com/codex/hooks) | matches |
| Codex hook output | SessionStart `additionalContext`; prompt guard `{"decision": "block", "reason": ...}` | SessionStart `hookSpecificOutput.additionalContext` (plain stdout also context); UserPromptSubmit `decision: "block"` or exit 2 (same page) | matches |
| Codex memories / goals (report only) | Reads `memories_1.sqlite` `stage1_outputs` | Memories are off by default, enabled with `[features] memories = true`; files under `~/.codex/memories/`, "generated state" (https://developers.openai.com/codex/memories). Goals: `/goal`, `features.goals` (https://developers.openai.com/codex/use-cases/follow-goals/). Upstream feature table: `memories` stable and off by default, `goals` stable and on by default (openai/codex `codex-rs/features/src/lib.rs`). The docs do not describe the `memories_1.sqlite` schema we read | unclear for the sqlite reader; not changed |

## Changes made

- `docs/COMMANDS.md`: Gemini memory import wording now says the heading comes from older versions.
- `tests/test_client_docs.py`: pins event names, nesting, every event's timeout units, Cursor `version`, MCP key names, the Cursor rule front matter, and non-Claude SessionStart context output. Prompt blocking (including Claude exit 2) is exercised by `tests/test_paste_guard.py`; Claude Stop output by `tests/test_finish_nudge.py`.
- No code changes were needed. README and SETUP compatibility tables are unchanged.
