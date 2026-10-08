# Workspace concepts

An AI Dev Workspace is a local folder that keeps useful project context between coding sessions. It is plain files plus the `ws` command; it does not host your code or make model calls by itself.

| Concept | In plain words | Example |
|---|---|---|
| Workspace | The folder holding project rules and memory. | `ws init ~/work/app-ws --repo ~/code/app` |
| Task record | A Markdown page for one piece of work. | `ws task new APP-1 "Fix login crash"` |
| Claim | A short lock showing who is working on a task. | `ws claim APP-1` |
| Checkpoint | The status and next step saved for another session. | `ws checkpoint APP-1 --status in_progress --next "Add the guard"` |
| Brief | A short summary of the active task and matching lessons. | `ws brief` |
| Capture | Claude Code and Codex hooks can capture supported transcript decisions; captured notes are unverified. | `ws connect claude` |
| Lesson | A reusable rule saved after learning something. | `ws lesson add "Guard empty emails" --tag auth` |
| Routing | The configured provider choice for a role. | `ws route explorer` |
| Delegate | Prepare a bounded, read-only worker request for review. | `ws delegate APP-1 --role explorer` |
| Assist | See local improvement suggestions and decide before applying. | `ws assist` |
| Pack | An optional set of domain-specific files and tools. | `ws packs` |

Claims prevent overlapping edits to one task record. A checkpoint gives the next session a concrete next step. Delegation only prepares work unless you explicitly choose a supported run option; the lead still reviews any worker output.

## Client compatibility

| Capability | Claude Code | Codex | Cursor | Copilot | Gemini CLI |
|---|---|---|---|---|---|
| Rules | proven | proven | documented, untested | documented, untested | documented, untested |
| MCP tools | proven | proven | documented, untested | documented, untested | documented, untested |
| Hooks | proven | proven | documented, untested | not available | documented, untested |
| Skills | proven | proven | not available | not available | not available |
| Automatic capture | proven | proven | documented, untested | not available | documented, untested |
