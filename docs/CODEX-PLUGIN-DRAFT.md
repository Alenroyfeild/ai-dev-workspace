# Codex plugin draft: native MCP binding pending

Do not install this draft for everyday use. The compatibility manifest in
`.codex-plugin/plugin.json` declares SessionStart, PreCompact, UserPromptSubmit
and Stop hooks for the approved runtime now on dev. Isolated Python startup
excludes repo and PYTHONPATH modules; paths never become shell code.

A disposable native Codex0.155.1 session received the saved decision from the
plugin hook with repo-local Codex wiring disabled. Hook trust was bypassed for
that test invocation; persisted interactive trust was not proved.
The same session could not call the bundled MCP brief or save a decision.

Codex passed `${CLAUDE_PLUGIN_ROOT}` literally in MCP args. Its MCP process
preserved the repo cwd, but exposed no PLUGIN_ROOT/CLAUDE_PLUGIN_ROOT variable.
The rejected declaration is removed. No MCP server or source marketplace is
advertised until a supported plugin-root and session-repo binding is proved.
Changing MCP cwd to the plugin cache would disconnect workspace discovery.

Use the plugin or `ws start`'s Codex hooks, not both: additive hooks can produce
duplicate briefs and captures. This draft does not remove existing repo wiring
or infer plugin enablement from `plugins."plugin@marketplace".enabled`.

[OpenAI packaging guidance](https://developers.openai.com/plugins/build/plugins)
covers local marketplaces and hook trust. The [Codex MCP loader](https://github.com/openai/codex/blob/main/codex-rs/codex-mcp/src/plugin_config.rs)
resolves relative configured cwd against the plugin root; it does not expand
plugin-root variables in args. [Hook documentation](https://learn.chatgpt.com/docs/hooks)
describes the four events and additive sources. Claude runs the Claude half.
