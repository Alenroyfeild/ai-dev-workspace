# Changelog

## 0.1.0-beta.1

This beta gives you a small, local workspace for carrying task context between coding sessions.

### What you can do

- Keep tasks, claims, checkpoints, lessons and session notes in plain files. Claude Code and Codex can load workspace rules, skills and MCP tools.
- Let Claude Code and Codex capture decisions from their session transcripts automatically. Captures are unverified and can be reviewed in the task record.
- Map a code checkout and search its map, notes and local session history. `ws map` can link an existing Graphify report; it never runs Graphify.
- Route work with `ws route` and run a bounded, read-only explorer with `ws delegate`. Run `ws delegate --selftest --provider codex` to check the current sandbox before using it.
- Browse the toolbox, see estimated tool load with `ws tools --cost`, and ask `ws assist` for improvements before applying them. Upgrade existing workspaces with `ws upgrade`; user content is preserved and conflicts are staged as `.ws-new`.
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

- macOS and Linux are supported; Windows is not supported yet because file locking uses `fcntl`.
- Automatic decision capture is proven for Claude Code and Codex; Cursor and Gemini CLI are wired but untested. Captured decisions are unverified.
- Cursor, Copilot and Gemini CLI connections are documented but have not been tested in live client sessions.
