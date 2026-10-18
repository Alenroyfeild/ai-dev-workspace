# Codex plugin: review pending

The compatibility manifest `.codex-plugin/plugin.json` declares SessionStart,
PreCompact, UserPromptSubmit and Stop hooks plus the stdio MCP entry in
`mcp/codex-plugin.json`. It reuses the approved plugin runtime on dev.
`--plugin` resolves memory from the session repo; no MCP cwd override points at
the plugin cache. Outside a started repo, only the inactive `brief` tool is listed.

Python startup is isolated for both hooks and MCP. Hook commands read
`CLAUDE_PLUGIN_ROOT` through Python so paths never become shell code.
Codex requires review and trust of installed hook definitions. Native loading
and memory delivery must pass before this draft is enabled for distribution.

Use the plugin or `ws start`'s Codex repo wiring, not both: duplicate hooks can
produce duplicate briefs and captures. This change does not remove repo wiring
or infer plugin enablement. Codex records local plugin state under
`plugins."plugin-name@marketplace-name".enabled`; that alone is not a ws receipt.
No source marketplace advertises this package yet.

[OpenAI packaging guidance](https://developers.openai.com/plugins/build/plugins)
covers compatibility manifests, local marketplaces and plugin trust.
[Bundled MCP configuration](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins)
uses the compatibility manifest's `mcpServers` path.
[Hook documentation](https://learn.chatgpt.com/docs/hooks) describes the events
and additive hook sources. Hook packages target local distribution rather than
the universal public directory. Prove the Codex half in a disposable HOME;
Claude runs the Claude half.
