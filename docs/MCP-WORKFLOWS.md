# Workflows through MCP

Clients without workspace skills can discover `handoff`, `pickup` and `lesson`
with `prompts/list` and retrieve one with `prompts/get` and its `name`. Each
returns the exact shipped skill steps as a user message; no arguments are needed.
Selecting a prompt supplies instructions; it does not execute them.

`resources/list` offers `workspace://brief` and `workspace://tasks/<ID>` for
tasks claimed in this workspace. `resources/read` returns the current brief or
task Markdown, redacted. Released or foreign claims are not task resources.
Clients should list again after claim changes and read again after checkpoints;
subscriptions and change notifications are not advertised.

Protocol contracts: official MCP [prompts specification](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)
and [resources specification](https://modelcontextprotocol.io/specification/2025-11-25/server/resources).
