
Read AGENTS.md for repo rules when it exists.
Private task memory: {{WORKSPACE}}
At session start, run `python3 {{OLD_KIT}}/bin/ws --workspace-root {{WORKSPACE}} brief` unless saved task memory is already in context. Follow the current request. Save verified decisions and next actions with `python3 {{OLD_KIT}}/bin/ws --workspace-root {{WORKSPACE}} checkpoint`.
When the user states a decision or corrects an earlier one, call the MCP `remember` tool with it; for a correction, say what it replaces.
