# Changelog

## 0.1.0-beta.3 (unreleased)

### Proven
- In this small-n rollout check, workspace runs passed 4/5, Markdown-only runs 3/5, and the baseline 0/5; four attempts were inconclusive. See [the method and limitations](docs/MEASUREMENTS.md).

### New
- `ws setup` previews assistant choices and project connections before applying them, and reports setup failures with next steps.
- Shared workspaces show tasks and claims matched to the current branch and flag conflicting task records.
- Session briefs carry an explicit saved handoff decision into the next session.
- `ws doctor --mcp` checks configured clients; `ws doctor` shows configuration separately from the latest protocol check and capture outcome.
- Maintainers can read recent repository stars, clones and page views in the activity report.

### Fixed
- Task records preserve CRLF line endings, and team claims and conflicts remain readable across shared work.
- The Claude rollout benchmark uses a per-trial home and allowlisted environment so shell credentials and user settings are not passed into project hooks. API-key-only authentication and live Claude runs were not verified.
- The benchmark fixture no longer races Git's automatic maintenance lock on macOS.
- TEAM claim examples and checkpoint help now match the supported commands and note sections; README, TEAM and SETUP quick-start commands are smoke-tested in throwaway workspaces.

## 0.1.0-beta.2 (2026-10-09)

### Proven
- Decisions given in Claude Code were followed by Codex in 5/5 runs with the workspace and 0/5 without (benchmark `--resume-provider`); Claude Code to Claude Code also 5/5 vs 0/5. See docs/MEASUREMENTS.md.

### New
- Stale-memory check: the brief warns when files named in the next action changed since the checkpoint, or when the code was rolled back past it; lessons whose files are gone are marked.
- `ws next`, `ws task depend` and `ws task import` (Spec Kit `tasks.md`, Task Master `tasks.json`).
- Copilot and Cursor get the current task in their own instruction files.
- `ws import native` reads Claude, Codex and Gemini built-in memories into a task (read-only, preview first); `ws status` shows Codex goal status.
- Privacy: `<private>` text and `#private` messages are never captured, home paths become `~`, more secrets are redacted, and `"capture": false` turns capture off.
- `ws paste` and `ws digest --focus` keep big logs out of the conversation.
- A session that changed files without updating its task is asked once to checkpoint.
- Plain, readable output in a terminal (JSON when piped or with `WS_JSON=1`).

### Fixed
- The session-start brief now keeps every numbered decision (a regression that hid them from non-Claude clients).
- First-run: `ws init` no longer prints a Codex config block to everyone; new workspaces are not offered selftest or install suggestions.

## 0.1.0-beta.1

This beta gives you a small, local workspace for carrying task context between coding sessions.

### What you can do

- Keep tasks, claims, checkpoints, lessons and session notes in plain files. Claude Code and Codex can load workspace rules, skills and MCP tools.
- Capture decisions from supported session transcripts; every capture is unverified and can be reviewed in the task record.
- Map a code checkout and search its map, notes and local session history. `ws map` can link an existing Graphify report; it never runs Graphify.
- Route work with `ws route` and run a bounded, read-only explorer with `ws delegate`. Run `ws delegate --selftest --provider codex` to check the current sandbox before using it.
- Browse the toolbox, see estimated tool load with `ws tools --cost`, and review `ws assist` suggestions before applying them. Upgrade existing workspaces with `ws upgrade`; user content is preserved and conflicts are staged as `.ws-new`.
- Use MCP prompts in clients without native skills, keep private packs locally, or delegate a read-only review of a diff. Security checks protect workspace paths and client configuration.
- Search Cursor and Gemini CLI session history, run the `bench/` continuity benchmark, and use grouped help or `--text` output in scripts. Cursor and Gemini session search are fixture-tested; client sessions remain untested live.
- Install the CLI with `pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace`.

In a measured test where Claude captured decisions automatically, the next session met all six hidden checks in 5/5 runs, versus 0/5 without the workspace. See [the method and limitations](docs/MEASUREMENTS.md).

### Client support

| Client | Status |
|---|---|
| Claude Code | Proven: rules, MCP tools, hooks, skills and automatic capture. |
| Codex | Proven: rules, MCP tools, hooks, skills and automatic capture. |
| Cursor | Rules, MCP tools, hooks and capture set up by `ws connect cursor`; untested live. |
| GitHub Copilot in VS Code | Rules and MCP tools set up by `ws connect vscode`; untested live. |
| Gemini CLI | Rules, MCP tools, hooks and capture set up by `ws connect gemini`; untested live. |

### Known limits

- Windows is supported; see [Windows notes](docs/WINDOWS.md).
- Captures are unverified and need review.
- Cursor, Copilot and Gemini CLI connections are documented but have not been tested in live client sessions.
