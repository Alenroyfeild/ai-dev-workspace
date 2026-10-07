# Commands

Every command works from inside a workspace folder (or with `WS_ROOT` set). Most print JSON.

## Set up

| Command | Does |
|---|---|
| `ws init <dir> [--name N] [--repo R] [--pack P]` | Create a workspace named for its folder unless `--name` is supplied. Never overwrites your files: conflicts are written beside them as `.ws-new`. With `--repo`, also writes the codebase map. |
| `ws connect claude\|codex\|cursor` | Connect an assistant: MCP config, plus the `/handoff`, `/pickup`, `/lesson` and `/thinkbeforeact` skills for Claude and Codex (existing skill names are kept). Codex: prints the config block; `--write` appends it with a backup. |
| `ws tools [--cost]` | List recommended, optional and caution tools; `--cost` reports MCP schema bytes, skill/plugin metadata size and cached Codeburn use over 30 days. |
| `ws doctor` | What is installed, which assistants are connected, what is missing under the active tool profile and overrides. |
| `ws packs` / `ws pack add <name>` | List and add optional packs. |
| `ws map [<repo>]` | Rewrite the codebase map; link an existing `graphify-out/GRAPH_REPORT.md` and its top headings. `ws search` includes that report. The kit never runs Graphify. |

## Daily loop

Claude Stop and PreCompact hooks capture cue-bearing decisions and the latest assistant summary from Claude transcripts only. Captures are redacted, appended and unverified; use `/handoff` for precise notes. remains under review.

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

Toolbox levels: recommended tools are suggested for most workspaces, optional tools add specific capabilities, and caution tools can change routing or configuration. Nothing is installed automatically.

## Measure and maintain

`ws route [role]` resolves a binding from `routing.json` (default lead); availability means only the selected CLI is on PATH and a model is configured, not that login/model access was checked. The first preference is authoritative: missing providers stop, never silently fall back. Set root `role_overrides` for provider/preference, tier, family, model or effort; edit the managed defaults only if you intend an upgrade to replace them. Claude family aliases and explicit Codex model IDs are configurable. Set an installed local model before using Ollama; ws never pulls models.

`ws delegate <task> --role <role>` saves a redacted brief of at most 400 words and prints an exact stdin/output command. Only explorer/reviewer support `--run` (routing timeout, default 600 seconds); all other roles are preparation-only, and printed commands also use read-only controls. Codex runs with read-only sandbox, no approvals, hooks/apps/plugins disabled and user config ignored. Claude uses project-only settings and only Read/Glob/Grep; Ollama is preparation-only. Allowed paths are prompt scope, not a read-access jail. Output stays UNVERIFIED in `.ws/briefs/`, a short summary appends to Evidence, and trace records role/model/effort/time/result, never a review acceptance. Lead decides/reviews. MCP route/delegate prepare only and reject run arguments. Upgrade adds managed routing defaults while preserving root overrides; unmarked routing files get proposals. No credential inspection, automatic dispatch or installation.

`ws delegate <task> --role reviewer --diff HEAD~1..HEAD [--run]` includes a diff stat, changed files and bounded hunks in the same 400-word brief; hunks may be truncated, so the reviewer can inspect the listed files read-only. Revisions must resolve to commits; a single revision compares against the working tree. Git external diff/text-conversion helpers are disabled and content is redacted. Reviewer output is one plain `UNVERIFIED file:line: problem. fix.` line per finding. Distinct matching lines are counted in `ws trace`; the count is unverified, never an acceptance. MCP delegate accepts optional diff for preparation only.

`ws delegate --selftest [--provider codex|claude]` tests the bound explorer using the same command as delegation, exclusively in a new throwaway tree. Codex runs; Claude prepares only unless `--run` explicitly opts in. A standalone random-token read is the positive control; hostile probes request patch, shell, Python, absolute, symlink, parent-path and Git commit writes. Disk content, modes, directory entries and modification times are compared independently. `SELFTEST OK` exits 0 only after a successful worker/token read and unchanged disk; mutations yield `FAIL` (1), missing reads/failed workers or preparation-only yield `INCONCLUSIVE` (2). Git is required for execution. Executed fixtures are removed; prepared fixtures remain for manual use and cleanup. `.ws/delegate-selftests.json` stores each provider's latest date/result for doctor; it is historical evidence, not a security guarantee or execution gate.

`ws assist` offers at most two local suggestions and asks before applying. `ws assist decide <id> accepted|declined|snoozed|always [--until YYYY-MM-DD]` remembers permission in `.ws/assist.json`; declined hides it for 30 days. `ws assist apply <id>` runs only an accepted/always map or trace action. Other commands stay for review. Notices offer suggestions once, at most two total. Daily Codeburn cache data guides cost advice; protected built-ins, the workspace server, Graphy tools, in-use servers and tools pinned `on` are excluded. It never runs `codeburn optimize --apply`. and are pending review. Configure `tool_profile` as `lean` (core only), `standard` (recommended tools) or `full`; `tool_overrides` maps tool names to `on`, `off` or `ask`. These settings guide assist and doctor and never remove software.
`ws run import codeburn [--since YYYY-MM-DD] [--task ID]` imports local `codeburn.export.v2` records. Matches use canonical repo paths and task windows; ambiguous records are skipped. Input totals include cache reads/writes; reasoning tokens are not counted again. Re-importing a grown session updates its existing entry (task/session/provider/model key); task text stays unchanged, and run logs retain no raw exports or project paths. Missing Codeburn prints its install command but never installs it. Codeburn defaults to 30 days; use `--since` for more. See [its export implementation](https://github.com/getagentseal/codeburn/blob/main/src/export.ts). and are pending review.
`ws upgrade --dry-run` previews exact managed-file diffs and missing claim-directory creation without writing. `ws upgrade` applies the current kit's managed rules, hook handlers and project-local Claude/Codex handoff, pickup and lesson bodies, with prior changed files backed up under `.ws/backups/<UTC timestamp>/`. Markdown uses `ws:managed` begin/end markers carrying the kit version; hook objects use `statusMessage: ws:managed:<event>:<kit version>` so files remain valid JSON. Keep personal rules, settings and hooks outside those objects/blocks: their bytes stay unchanged. Unmarked or ambiguous files produce `.ws-new` proposals (numbered if an existing proposal was edited); review and adopt those manually, then rerun dry-run. `workspace.json` records schema 2, kit version, desired-content fingerprint and pending proposals while retaining custom keys and vault paths. An empty claim directory is created; existing claims are never adopted or changed. Runtime tools come from the updated kit; no tools or global skills are installed. Hook changes require client review/trust again. Symlink targets and newer schemas are refused. CLI only: no MCP upgrade tool. File writes are atomic with a workspace lock; the multi-file upgrade is not a single transaction.

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
