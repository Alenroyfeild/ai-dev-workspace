# Private memory from your repo

Run `ws start` inside the Git checkout. It previews every repo/private-workspace
file, asks once, and stores memory in ~/.ai-dev-workspace/<repo-name>. Use
`--workspace <dir>` to choose another external folder, or `--yes` for scripts.
The current branch names the automatically claimed task. Run it again for status.
New task IDs use a portable, shortened branch name, with a hash suffix only on collision. Existing branch tasks keep their IDs and saved text. Next action stays empty until you save a real checkpoint; setup does not count as remembered work.

Claude gets CLAUDE.local.md, settings.local.json and a project .mcp.json; Codex
gets AGENTS.override.md and project hooks. Git's local info/exclude keeps all
repo additions private. Tracked target files and symlinks are refused. Existing
repo rules remain in place; local pointers include/read AGENTS.md when present.
Trust hooks/MCP in each client when asked. No assistant is launched by setup.
Detected Cursor, VS Code/Copilot and Gemini are offered in that same confirmation.
Their repo hooks, MCP entries and private instruction files are Git-excluded;
tracked secondary instructions are kept. Copilot cloud agents require a committed
copy: setup explains this and never commits or silently shares instructions.

`ws start --undo` removes unchanged repo wiring, restores preexisting local
files and removes only its Git exclude block. Edited local files are kept and
reported; private memory outside the repo is retained. Nothing is committed.
Codex MCP configuration is the next separate change; existing ws connect works.

Sources: [Claude local memory](https://code.claude.com/docs/en/memory),
[local settings](https://code.claude.com/docs/en/settings),
[MCP scopes](https://code.claude.com/docs/en/mcp),
[Codex project instructions](https://developers.openai.com/codex/guides/agents-md/),
[project config](https://developers.openai.com/codex/config-basic/),
[hooks and trust](https://developers.openai.com/codex/hooks/),
[Cursor hooks](https://cursor.com/docs/hooks),
[VS Code local hooks](https://code.visualstudio.com/docs/agent-customization/hooks),
[Copilot instructions and harnesses](https://code.visualstudio.com/docs/agent-customization/custom-instructions),
[Gemini hooks](https://geminicli.com/docs/hooks/reference/).
