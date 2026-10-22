# Security policy

## Reporting a vulnerability

Report privately. Do not open a public issue.

Use the repository's **Security** tab, then **Report a vulnerability** (GitHub private vulnerability reporting). Include the steps to reproduce, the `ws version` output and the affected command or file. Remove secrets and private paths first.

## In scope

- Hooks that `ws` writes for assistants.
- The MCP server in `mcp/`.
- Team sharing: previews, approvals, and what leaves your machine.
- Redaction of captured text and shared notes.

## Redaction is heuristic

`ws` redacts common secret and path patterns, but it cannot catch everything. Review every preview before you approve a share or submit feedback.
