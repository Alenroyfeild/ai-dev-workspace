# Workspace concepts

An AI Dev Workspace is a local folder that keeps useful project context between coding sessions. It is plain files plus the `ws` command; it does not host your code or make model calls by itself.

| Concept | In plain words | Example |
|---|---|---|
| Workspace | The folder holding project rules and memory. | `ws init ~/work/app-ws --repo ~/code/app` |
| Task record | A Markdown page for one piece of work. | `ws task new APP-1 "Fix login crash"` |
| Claim | A short lock showing who is working on a task. | `ws claim APP-1` |
| Checkpoint | The status and next step saved for another session. | `ws checkpoint APP-1 --status in_progress --next "Add the guard"` |
| Brief | A short summary of the active task and matching lessons. | `ws brief` |
| Capture | Claude hooks can save decisions from its transcript; captured notes are unverified. | `ws connect claude` |
| Lesson | A reusable rule saved after learning something. | `ws lesson add "Guard empty emails" --path "src/auth/*" --area auth` |
| Routing | The configured provider choice for a role. | `ws route explorer` |
| Delegate | Prepare a bounded, read-only worker request for review. | `ws delegate APP-1 --role explorer` |
| Assist | See local improvement suggestions and decide before applying. | `ws assist` |
| Pack | An optional set of domain-specific files and tools. | `ws packs` |

Claims prevent overlapping edits to one task record. A checkpoint gives the next session a concrete next step. Delegation only prepares work unless you explicitly choose a supported run option; the lead still reviews any worker output.

Lesson paths are optional relative repo globs; repeat `--path` for multiple patterns. Briefs prefer lessons matching files changed from the task repo's commit at claim time (`git diff --name-only`), then title/area words, with at most three bounded lessons. The diff includes committed and tracked working changes, including any pre-existing edits; untracked files are not included. Old claims or unavailable Git fall back to title/area matching. Resuming a claim keeps its original commit.
