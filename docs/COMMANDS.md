# Commands

Every command works from inside a workspace folder (or with `WS_ROOT` set). Most print JSON.

## Set up

| Command | Does |
|---|---|
| `ws init <dir> [--name N] [--repo R] [--pack P]` | Create a workspace named for its folder unless `--name` is supplied. Never overwrites your files: conflicts are written beside them as `.ws-new`. With `--repo`, also writes the codebase map. |
| `ws connect claude\|codex\|cursor` | Connect an assistant: MCP config, plus the `/handoff`, `/pickup`, `/lesson` and `/thinkbeforeact` skills for Claude and Codex (existing skill names are kept). Codex: prints the config block; `--write` appends it with a backup. |
| `ws doctor` | What is installed, which assistants are connected, what is missing. |
| `ws packs` / `ws pack add <name>` | List and add optional packs. |
| `ws map [<repo>]` | Rewrite the codebase map (languages, build/test commands, folders, most-changed files). No model involved. |

## Daily loop

| Command | Does |
|---|---|
| `ws task new <ID> "<title>"` / `find` / `list` / `show <ID> --section "Next action"` | Task records. `show --section` reads only what you need. |
| `ws claim <ID> [--worker W]` | Take the task as `$USER` unless `--worker` is supplied. The claim is remembered locally, so the next commands need no token. |
| `ws checkpoint <ID> --status <s> --next "<exact next step>" [--note "Evidence=..."]` | Save progress and the exact next step. |
| `ws release <ID>` | Give the task back. |
| `ws brief` | The in-progress task's next action, blockers and matching lessons, in under 200 words. The session-start hook runs this. |
| `ws lesson add "<what happened → rule>"` / `ws lesson search "<words>"` | Lessons learned. |
| `ws search "<words>"` | Ranked snippets from the vault notes. |
| `ws sessions search "<words>"` | Search your past Claude Code and Codex conversations on this machine. Read-only, redacted snippets. |
| `ws digest <file>` | Deterministic summary of a big log or JSON file. |

## Measure and maintain

`ws assist` offers at most two local suggestions with evidence, command, safety and estimated saving. `ws assist decide <id> accepted|declined|snoozed|always [--until YYYY-MM-DD]` remembers permission in `.ws/assist.json`; declined hides it for 30 days. `ws assist apply <id>` executes only an accepted/always map or trace action. Other commands are shown for review, never executed. Always does not schedule automatic work. Notices offer suggestions once, at most two total. Cost advice uses local Codeburn reports and a 30-day connector-use export, filters protected/in-use servers and Graphy-related findings, and never runs optimize --apply. Missing usage evidence suppresses connector advice. Checkpoint/session counters begin with this version; a transcript over 2 MB prompts a handoff/fresh session.
`ws run import codeburn [--since YYYY-MM-DD] [--task ID]` imports `codeburn.export.v2` records from a temporary local export. Matches require canonical repository paths and task windows (claim/creation through completion, or now for unfinished work); ambiguous matches are skipped. Explicit task selection still checks path/time. Imports append source-tagged, deduplicated usage entries; task text is unchanged. Input totals include cache reads/writes; reasoning tokens are not counted again. Usage does not reset the repeat guard. Missing Codeburn prints its install command but never installs it. Raw exports and project paths are not retained in run logs. MCP `import_usage` accepts `since` and `task`. Existing imported records are snapshots; later revisions to an already-imported call are skipped. Codeburn's default export covers 30 days; use --since for a wider/custom window. See [official export implementation](https://github.com/getagentseal/codeburn/blob/main/src/export.ts).

| Command | Does |
|---|---|
| `ws run log <task> <step> --provider P [--tokens-in N ...]` / `ws run report [task]` | Per-step log of who did what, tokens, seconds and result. |
| `ws trace <task>` | Read-only Markdown timeline, including reported checks, verdicts and total tokens. Redirect stdout to save it. |
| `ws validate` / `ws status` | Health check / overview. |
| `ws feedback add "<text>"` / `list` / `submit N` / `sync` | Feedback about the workspace; `submit` turns one item into a GitHub issue after a redacted preview. |
| `ws notices` | New release, fixed issues, unshared feedback. Your assistant runs it once per session and asks before doing anything. |
| `ws update [--check]` | Update the kit (git clone) or print the pipx command (pipx install). |

## MCP tools

`ws run log` also accepts `--worker-role`, `--effort`, repeated `--check "<command>=<exit code>"`, `--files N`, `--verdict accepted|changes|rejected`, and `--findings N`. Counts must be nonnegative. Checks are caller-reported; commands are never executed. Records append to `vault/Runs/<task>.jsonl`; old records remain readable. Two consecutive steps on one task with failed/rejected results, changes/rejected verdicts, or nonzero check codes make `ws brief` and `ws nudge` warn: "stop: two failed attempts, re-diagnose before trying again". A later nonfailing step clears that task's warning; another task's steps do not. This is an advisory guard, not execution enforcement. Log actual token counts only when available; omitted counts retain the existing zero defaults.

`mcp/server.py` exposes 20 tools to any MCP client: `find_task`, `read_task`, `new_task`, `claim_task`, `release_task`, `checkpoint`, `brief`, `nudge`, `search_vault`, `search_lessons`, `add_lesson`, `search_sessions`, `codebase_map`, `digest_file`, `add_feedback`, `log_step`, `trace`, `notices`, `status`, `connect_client`. MCP `log_step` accepts the same metadata (`checks` is an array of `command=exit code` strings); `trace` takes `task`. Setup, pack installation and feedback submission stay CLI-only on purpose.
