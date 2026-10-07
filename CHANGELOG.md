# Changelog

## 0.1.0-beta.1

This beta gives you a small, local workspace for carrying task context between coding sessions.

### What you can do

- Keep tasks, claims, checkpoints, lessons and session notes in plain files. Claude Code and Codex can load workspace rules, skills and MCP tools.
- Let Claude Code capture decisions from its session transcript automatically. Captures are unverified and can be reviewed in the task record.
- Map a code checkout and search its map, notes and local session history. `ws map` can link an existing Graphify report; it never runs Graphify.
- Route work with `ws route` and run a bounded, read-only explorer with `ws delegate`. Run `ws delegate --selftest --provider codex` to check the current sandbox before using it.
- Browse the toolbox, see estimated tool load with `ws tools --cost`, and ask `ws assist` for improvements before applying them. Upgrade existing workspaces with `ws upgrade`; user content is preserved and conflicts are staged as `.ws-new`.
- Install the CLI with `pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace`.

In a measured test where Claude captured decisions automatically, the next session met all six hidden checks in 5/5 runs, versus 0/5 without the workspace. See [the method and limitations](docs/MEASUREMENTS.md).

### Client support

| Client | Status |
|---|---|
| Claude Code | Proven: rules, MCP tools, hooks and skills; automatic capture is Claude-only. |
| Codex | Proven: rules, MCP tools, hooks and skills. |
| Cursor | Documented, untested. |
| GitHub Copilot in VS Code | Documented, untested. |
| Gemini CLI | Documented, untested. |

### Known limits

- macOS and Linux are supported; Windows is not supported yet because file locking uses `fcntl`.
- Automatic decision capture reads Claude Code transcripts only. Captured decisions are unverified.
- Cursor, Copilot and Gemini CLI connections are documented but have not been tested in live client sessions.
