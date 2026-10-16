# Codex plugin draft: integration pending

Do not install this draft. It packages SessionStart/Stop hook declarations for
Sol-1's `bin/ws-plugin --client codex` runtime; that entrypoint is not on dev yet.
The fixture tests verify metadata and actual shell command execution with a
stand-in launcher. They do not prove native plugin loading or memory delivery.

The compatibility manifest lives in `.codex-plugin/plugin.json`; the repo catalog
in `.agents/plugins/marketplace.json` makes it available rather than required.
Commands read `CLAUDE_PLUGIN_ROOT` through Python so paths never become shell code.
Codex still requires the user to review and trust the installed hook definitions.
See [official OpenAI plugin packaging guidance](https://developers.openai.com/plugins/build/plugins).
Hook-bearing packages are currently ineligible for the universal public directory;
this draft targets a repo marketplace, not a public-directory submission.

Before enabling this package, integrate the approved runtime and verify native
MCP startup preserves the session's repo working directory. No MCP server is
declared here: assuming the plugin installation directory is the user's repo
would disconnect memory. Existing repo-local wiring remains required until
Sol-1 implements and tests plugin detection and avoiding duplicate wiring.

Then run native Codex installation/hook-trust/memory/clean-undo proof in a
throwaway HOME. Claude runs the corresponding Claude half. No real client
configuration or installs are needed for the draft's fixture tests.
