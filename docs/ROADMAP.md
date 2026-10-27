# Roadmap

The beta is usable for personal session memory and consent-based team sharing.
Compatibility claims stay limited to tested behavior; see the [client table](CLIENT-VERIFICATION.md).

## Available in the beta

- [x] Install from PyPI with `pipx install ai-dev-workspace --pip-args='--pre'` (see [Setup](SETUP.md)).
- [x] Keep tasks, decisions, lessons and handoff notes in Markdown you control.
- [x] Start, checkpoint, search and pick up work across sessions.
- [x] Connect Claude Code and Codex in one step (`ws start`); capture decisions from both clients' transcripts as unverified notes.
- [x] Share selected team knowledge after reviewing each preview, or read it from a linked synced folder (read-only).
- [x] Use local packs, workspace upgrades, codebase maps and permission-based assist.
- [x] Route and delegate read-only work with a disposable-workspace self-test.
- [x] Publish measured session-memory results with method and limits in [MEASUREMENTS.md](MEASUREMENTS.md).
- [x] Print a task's decisions and checks as a PR description, including tried-and-rejected approaches (`ws pr-notes`) and a weekly recap (`ws recap`).
- [x] Pull approved team notes automatically at session start, after consent.
- [x] Start lighter: 7 core MCP tools listed by default.
- [x] Refresh repo setup after an upgrade (`ws start` again), keeping your edits.
- [x] Warn in the brief when files named in the next action changed since the checkpoint, or the code was rolled back past it.
- [x] Carry dead ends into the brief (`Do not redo:`, from the task's Do not redo and Failures), and warn when saved memory names deleted or renamed files or uncommitted edits that were reset away.
- [x] Opt-in `guards` (blocks risky shell commands, secrets and skipped tests; `WS_GUARDS=off`) and advisory `discipline` hook packs for Claude Code and Codex.
- [x] Score a repo's AI assistant setup with `ws audit`, and try remembered decisions offline with `ws demo`.
- [x] **Claude Code Plugin** (Preview): install from this repo's marketplace (see [Advanced](ADVANCED.md#claude-code-plugin-preview)).
- [x] **Codex Plugin** (Preview): `.codex-plugin/plugin.json` and `hooks/codex-hooks.json` (see [Advanced](ADVANCED.md#codex-plugin-preview)).
- [x] **Cursor Plugin** (Preview): `.cursor-plugin/plugin.json`, `hooks/cursor-hooks.json`, and generated rules `.mdc` (see [Advanced](ADVANCED.md#cursor-plugin-preview)).
- [x] **Worker Provider Fallback** (Preview): for `ws delegate --run`, retries the next declared headless provider if a CLI errors, times out, or returns a quota rejection.
- [x] **OpenAI-Compatible Gateway Provider** (Preview): configure an OpenAI-compatible `base_url` provider for read-only delegation (see [Advanced](ADVANCED.md#openai-compatible-gateway-preview)).
- [x] **Compact MCP Recall**: MCP `search_vault` returns compact IDs, titles, and dates first; pass a selected ID as `detail` for full bounded content without enlarging the seven-tool core catalog (see [Advanced](ADVANCED.md#compact-mcp-recall)).
- [x] **Lesson Promotion Drafts**: `ws lesson promote <id>` suggests explicit, inactive rule drafts from repeated lessons or dead ends without altering active project rules (see [Advanced](ADVANCED.md#draft-a-rule-from-repeated-lessons)).
- [x] **Lesson Review**: `ws lesson review [--days N]` lists old lesson date stamps for manual review without changing or deleting saved lessons.
- [x] **Opt-in Behavior Pack**: `ws pack add behavior` installs concise cross-client engineering guidelines (think first, minimal changes, surgical edits, verify work) into `AGENTS.md`; cleanly removable with `ws pack remove behavior` (see [Packs](PACKS.md#behavior-guidelines)).
- [x] **Opt-in Digest Pack** (Preview): advertises `digest_file` over MCP and emits an advisory size hint for tool outputs exceeding 40 KB (see [Packs](PACKS.md#optional-digest-advice)).
- [x] **Antigravity Session Hooks** (Preview): configures `.agents/hooks.json` with `SessionStart` brief injection and `PreToolUse` safety guards (see [Client Verification](CLIENT-VERIFICATION.md)).
- [x] **claude-mem Import** (Preview): `ws import claude-mem --db <file> --project <name>` previews checkpointed claude-mem SQLite copies read-only with safety allowlists and caps (see [Advanced](ADVANCED.md#import-a-claude-mem-copy)).

## Next

- [ ] List the MCP server in the official registry (server.json ready, the maintainer publishes).
- [ ] Test Cursor, Copilot and Gemini CLI in live client sessions.
- [ ] Add automatic decision capture only where another client exposes a suitable transcript or equivalent.
- [ ] Prepare the public v0.2 launch from beta feedback and test results.

## Later, if users need it

- [ ] Consider write-capable assistant workers only after the isolation checks pass.
- [ ] Add analytics or vector search only if current notes and search do not meet real needs.

## Not planned

- A hosted service or database. The workspace stays centered on local files and small tools.
