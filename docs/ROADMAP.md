# Roadmap

The beta is usable for personal session memory and consent-based team sharing.
Compatibility claims stay limited to tested behavior; see the [client table](CLIENT-VERIFICATION.md).

## Available in the beta

- [x] Keep tasks, decisions, lessons and handoff notes in Markdown you control.
- [x] Start, checkpoint, search and pick up work across sessions.
- [x] Connect Claude Code and Codex in one step (`ws start`); capture decisions from both clients' transcripts as unverified notes.
- [x] Share selected team knowledge after reviewing each preview.
- [x] Use local packs, workspace upgrades, codebase maps and permission-based assist.
- [x] Route and delegate read-only work with a disposable-workspace self-test.
- [x] Publish measured session-memory results with method and limits in [MEASUREMENTS.md](MEASUREMENTS.md).
- [x] Print a task's decisions and checks as a PR description (`ws pr-notes`) and a weekly recap (`ws recap`).
- [x] Pull approved team notes automatically at session start, after consent.
- [x] Start lighter: 7 core MCP tools listed by default.
- [x] Refresh repo setup after an upgrade (`ws start` again), keeping your edits.

## Next

- [ ] Install from PyPI (`pipx install ai-dev-workspace`) and list the MCP server in the official registry.
- [ ] Carry failed approaches into the next session's brief, and warn when saved memory names files that were deleted or work that was reset.
- [ ] `ws audit` for a repo's AI setup, and opt-in guard and discipline hook packs.

- [ ] Test Cursor, Copilot and Gemini CLI in live client sessions.
- [ ] Add automatic decision capture only where another client exposes a suitable transcript or equivalent.
- [ ] Prepare the public v0.2 launch from beta feedback and test results.

## Later, if users need it

- [ ] Consider write-capable assistant workers only after the isolation checks pass.
- [ ] Add analytics or vector search only if current notes and search do not meet real needs.

## Not planned

- A hosted service or database. The workspace stays centered on local files and small tools.
