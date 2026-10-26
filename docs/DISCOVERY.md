# Discovery metadata (LA4c)

GitHub settings below are a maintainer proposal, not applied by this PR.
The current README opening already explains shared memory for Claude Code and
Codex; the separate RM1 README work owns its wider layout and claims.

| Setting | Proposed value |
|---|---|
| Description | Shared Markdown task memory for Claude Code and Codex. Save decisions, next steps and dead ends across sessions. |
| Homepage | https://github.com/Alenroyfeild/ai-dev-workspace/blob/main/docs/TUTORIAL.md |
| Topics | Keep existing topics; add `ai-memory`, `agent-skills`, `antigravity`. |

The existing topics checked on 2026-10-23 are `agent-memory`, `agents-md`,
`ai-agents`, `ai-coding-assistant`, `claude-code`, `codex`, `context-engineering`,
`cursor`, `developer-tools`, `gemini-cli`, `github-copilot`, `llm`, `mcp`, and
`model-context-protocol`. No hosted website or directory indexing is implied.
Antigravity hooks are a Preview in beta.6, fixture-tested rather than live-checked.

`setup.py` adds the three search terms plus Tutorial and Client verification URLs.
These are metadata for the next package release; this PR does not change PyPI.
[Published PyPI metadata](https://pypi.org/project/ai-dev-workspace/0.1.0b5/)
was checked against the beta.5 README before drafting the summaries.

[llms.txt](../llms.txt) is the short entry point; [llms-full.txt](../llms-full.txt)
adds workflow and plugin-preview details. Links use main; unreleased work is listed
under Coming next without links. They describe existing behavior
and limits without claiming guaranteed recall, savings or directory acceptance.
The maintainer submits registry/directory entries and applies repository settings.
