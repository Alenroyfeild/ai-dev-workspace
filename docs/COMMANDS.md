# Commands

Every command works from inside a workspace folder (or with `WS_ROOT` set). In a terminal they print plain lines; piped output is JSON, and `WS_JSON=1` forces JSON.

## Set up

| Command | Does |
|---|---|
| `ws init <dir> [--name N] [--repo R] [--pack P]` | Create a workspace named for its folder unless `--name` is supplied. Never overwrites your files: conflicts are written beside them as `.ws-new`. With `--repo`, also writes the codebase map. |
| `ws connect claude\|codex\|cursor\|vscode\|gemini` | Connect an assistant: MCP config, plus the `/handoff`, `/pickup`, `/lesson` and `/thinkbeforeact` skills for Claude and Codex (existing skill names are kept). Codex: prints the config block; `--write` appends it with a backup. |
| `ws tools [--cost]` | List recommended, optional and caution tools; `--cost` reports MCP schema bytes, skill/plugin metadata size and cached Codeburn use over 30 days. |
| `ws doctor` | What is installed, which assistants are connected, what is missing under the active tool profile and overrides. |
| `ws packs` / `ws pack add <name>` | List and add optional packs. |
| `ws map [<repo>]` | Rewrite the codebase map; link an existing `graphify-out/GRAPH_REPORT.md` and its top headings. `ws search` includes that report. The kit never runs Graphify. |

## Daily loop

Claude and Codex hooks can capture cue-bearing decisions and assistant summaries from supported transcripts. Captures are redacted and unverified; use `/handoff` for precise notes.

| Command | Does |
|---|---|
| `ws task new <ID> "<title>"` / `find` / `list` / `show <ID> --section "Next action"` | Task records. `show --section` reads only what you need. |
| `ws task depend <ID> --on <OTHER>` | Make `<ID>` wait for `<OTHER>` (stored as `depends_on: A-1, A-2` in the task header). Both tasks must exist; self-dependencies and cycles are refused. |
| `ws next [--json]` | Open tasks (not done, not blocked) whose dependencies are all done, in_progress first, then review, ready, backlog. Each line: `ID status title (unblocks: X, Y)`, then `N waiting on dependencies`. |
| `ws task import <file> [--prefix SPEC] [--yes]` | Create tasks from a Task Master `tasks.json` (`tasks` list or `{"master": {"tasks": [...]}}`; subtasks are not imported) or a Spec Kit style `tasks.md` (`- [ ] T001 ...`, `- [x]` = done, optional `(depends on T001, T002)`). IDs become `SPEC-1` / `SPEC-T001`. Preview by default, `--yes` writes; existing IDs are skipped and reported, never overwritten; unknown dependencies or cycles block the write. Task Master `done` maps to done, `in-progress` to in_progress, `review`/`blocked` as is, `deferred`/`cancelled` to backlog, everything else to ready. |
| `ws claim <ID> [--worker W]` | Take the task as `$USER` unless `--worker` is supplied. The claim is remembered locally, so the next commands need no token. |
| `ws checkpoint <ID> --status <s> --next "<exact next step>" [--note "Evidence=..."]` | Save progress and the exact next step. |
| `ws release <ID>` | Give the task back. |
| `ws brief` | Task memory in under 200 words: next action, explicit saved Handoff, blockers, unverified automatic captures and matching lessons. Explicit Handoff is labelled as saved task-record text, separate from captures; long notes retain their latest words. `[truncated]` labels bounded fields or omitted context; read the task's sections for the full source. Existing Copilot/Cursor native blocks receive the same brief on checkpoint or `ws brief --refresh`. The session-start hook also runs this. `Memory check` flags changed/undone code; unmatched lesson paths show `(paths gone)`, and more than three matches collapse to `Lessons: N more`. |
| `ws lesson add "<what happened → rule>"` / `ws lesson search "<words>"` | Lessons learned. |
| `ws search "<words>"` | Ranked snippets from the vault notes. |
| `ws sessions search "<words>"` | Search local Claude Code, Codex, Cursor and Gemini transcripts with read-only, redacted snippets. |
| `ws import native [--client claude\|codex\|gemini\|all] [--task ID] [--yes]` | Preview (max 20 redacted lines) memories the assistants saved natively. Claude: `~/.claude/projects/<folder>/memory/*.md` for the workspace and each configured repo folder. Codex: `stage1_outputs` rollout summaries in `$CODEX_HOME/memories_1.sqlite` whose slug or raw memory names the workspace or repo folder. Gemini CLI: the `## Gemini Added Memories` lines of `~/.gemini/GEMINI.md` (written by older `save_memory`/`/memory add`; current Gemini CLI docs say the agent edits memory Markdown files directly, including a private per-project folder whose format is undocumented, so newer entries are not imported). `--yes` appends one `### Imported <date> (unverified, from <client>)` block per client to the task Handoff (`--task`, else the single in-progress task): redacted, at most 150 words per client, skipped when already there. Native stores are only read. |
| `ws paste` | Save clipboard text (or piped stdin) redacted in `.ws/inbox/`, then print only its digest. |
| `ws digest <file> [--focus <regex>] [--local-summary]` | Show bounded context around matching lines first (bounded regex, scans the first 4096 characters per line), then the deterministic digest. `--local-summary` requires the `local-llm` pack. |

`ws connect` installs a prompt-size guard for Claude Code (`UserPromptSubmit`), Codex (`UserPromptSubmit`), Cursor (`beforeSubmitPrompt`) and Gemini CLI (`BeforeAgent`). Prompts over 150 lines or 12 KB are saved redacted in `.ws/inbox/` and blocked; send a short question with the relevant excerpt, or put `!raw` alone on the first line to bypass. These clients document blocking prompt hooks: [Claude Code](https://code.claude.com/docs/en/hooks), [Codex](https://learn.chatgpt.com/docs/hooks), [Cursor](https://cursor.com/docs/hooks), and [Gemini CLI](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md).

Toolbox levels: recommended tools are suggested for most workspaces, optional tools add specific capabilities, and caution tools can change routing or configuration. Nothing is installed automatically.

## Measure and maintain

`ws route [role]` shows the configured binding and whether its CLI/model setting is available. Availability does not verify login or account access. Advanced routing and tool settings: [ADVANCED.md](ADVANCED.md).

`ws delegate <task> --role <role>` prepares a redacted brief of at most 400 words and prints an exact stdin/output command. Only explorer/reviewer support `--run` (routing timeout, default 600 seconds); all other roles are preparation-only, and printed commands also use read-only controls. Codex runs with read-only sandbox, no approvals, hooks/apps/plugins disabled and user config ignored. Claude uses project-only settings and only Read/Glob/Grep; Ollama is preparation-only. Allowed paths are prompt scope, not a read-access jail. Output stays UNVERIFIED in `.ws/briefs/`, a short summary appends to Evidence, and trace records role/model/effort/time/result, never a review acceptance. Lead decides/reviews. MCP route/delegate prepare only and reject run arguments. Upgrade adds managed routing defaults while preserving root overrides; unmarked routing files get proposals. No credential inspection, automatic dispatch or installation.

`ws delegate <task> --role reviewer --diff HEAD~1..HEAD [--run]` includes a diff stat, changed files and bounded hunks in the same 400-word brief; hunks may be truncated, so the reviewer can inspect the listed files read-only. Revisions must resolve to commits; a single revision compares against the working tree. Git external diff/text-conversion helpers are disabled and content is redacted. Reviewer output is one plain `UNVERIFIED file:line: problem. fix.` line per finding. Distinct matching lines are counted in `ws trace`; the count is unverified, never an acceptance. MCP delegate accepts optional diff for preparation only.

`ws delegate --selftest [--provider codex|claude]` tests the bound explorer using the same command as delegation, exclusively in a new throwaway tree. Codex runs; Claude prepares only unless `--run` explicitly opts in. A standalone random-token read is the positive control; hostile probes request patch, shell, Python, absolute, symlink, parent-path and Git commit writes. Disk content, modes, directory entries and modification times are compared independently. `SELFTEST OK` exits 0 only after a successful worker/token read and unchanged disk; mutations yield `FAIL` (1), missing reads/failed workers or preparation-only yield `INCONCLUSIVE` (2). Git is required for execution. Executed fixtures are removed; prepared fixtures remain for manual use and cleanup. `.ws/delegate-selftests.json` stores each provider's latest date/result for doctor; it is historical evidence, not a security guarantee or execution gate.

`ws assist` offers up to two local workspace suggestions and asks before applying. Tool installation suggestions are available through the explicit `ws tools` catalog. Permission and cost settings are in [ADVANCED.md](ADVANCED.md).
`ws upgrade --dry-run` previews exact managed-file diffs and missing claim-directory creation without writing. `ws upgrade` applies the current kit's managed rules, hook handlers and project-local Claude/Codex handoff, pickup and lesson bodies, with prior changed files backed up under `.ws/backups/<UTC timestamp>/`. Markdown uses `ws:managed` begin/end markers carrying the kit version; hook objects use `statusMessage: ws:managed:<event>:<kit version>` so files remain valid JSON. Keep personal rules, settings and hooks outside those objects/blocks: their bytes stay unchanged. Unmarked or ambiguous files produce `.ws-new` proposals (numbered if an existing proposal was edited); review and adopt those manually, then rerun dry-run. `workspace.json` records schema 2, kit version, desired-content fingerprint and pending proposals while retaining custom keys and vault paths. An empty claim directory is created; existing claims are never adopted or changed. Runtime tools come from the updated kit; no tools or global skills are installed. Hook changes require client review/trust again. Symlink targets and newer schemas are refused. CLI only: no MCP upgrade tool. File writes are atomic with a workspace lock; the multi-file upgrade is not a single transaction.

`ws run import codeburn [--since YYYY-MM-DD] [--task ID]` imports local usage records. Re-importing a grown session updates its existing entry; run logs omit raw exports and project paths. CodeBurn defaults to 30 days; use `--since` for a wider range. See [ADVANCED.md](ADVANCED.md) for matching and accounting details.

| Command | Does |
|---|---|
| `ws run log <task> <step> --provider P [--tokens-in N ...]` / `ws run report [task]` | Per-step log of who did what, tokens, seconds and result. |
| `ws trace <task>` | Read-only Markdown timeline, including reported checks, verdicts and total tokens. Redirect stdout to save it. |
| `ws validate` / `ws status` | Health check / overview. When Codex goals exist (`$CODEX_HOME/goals_1.sqlite`), `ws status` and `ws doctor` show `Codex goals: N active, M complete` for goals whose objective mentions an in-progress task ID or title, and `ws checkpoint --status done` prints a hint on stderr while one is still active. Read-only; close goals in Codex. Missing or unrecognised files are skipped (doctor says why). |
| `ws feedback add "<text>"` / `list` / `submit N` / `sync` | Feedback about the workspace; `submit` turns one item into a GitHub issue after a redacted preview. |
| `ws notices` | New release, fixed issues, unshared feedback. Your assistant runs it once per session and asks before doing anything. |
| `ws update [--check]` | Update the kit (git clone) or print the pipx command (pipx install). |

## MCP tools

`ws run log` also accepts `--worker-role`, `--effort`, repeated `--check "<command>=<exit code>"`, `--files N`, `--verdict accepted|changes|rejected`, and `--findings N`. Counts must be nonnegative. Checks are caller-reported; commands are never executed. Records append to `vault/Runs/<task>.jsonl`; old records remain readable. Two consecutive steps on one task with failed/rejected results, changes/rejected verdicts, or nonzero check codes make `ws brief` and `ws nudge` warn: "stop: two failed attempts, re-diagnose before trying again". A later nonfailing step clears that task's warning; another task's steps do not. This is an advisory guard, not execution enforcement. Log actual token counts only when available; omitted counts retain the existing zero defaults.

`mcp/server.py` exposes 24 tools: `route`, `delegate`, `assist`, `import_usage`, `search_sessions`, `codebase_map`, `brief`, `nudge`, `connect_client`, `find_task`, `read_task`, `new_task`, `claim_task`, `release_task`, `checkpoint`, `search_vault`, `search_lessons`, `add_lesson`, `add_feedback`, `digest_file`, `log_step`, `trace`, `notices`, and `status`. MCP `log_step` accepts the same metadata (`checks` is an array of `command=exit code` strings); `trace` takes `task`. Setup, pack installation and feedback submission stay CLI-only on purpose.


### Select assistants

After `ws init`, run `ws setup` to choose assistants interactively, or `ws setup --assistants codex` / `ws setup --assistants claude,codex` / `ws setup --preset cursor-only`. `ws setup --detect` only checks CLI names on PATH and macOS app paths; it never launches clients or checks login. Other platforms have CLI detection and manual app selection.

Setup backs up routing/workspace metadata in `.ws/backups/`, preserves user text and compatible overrides, then connects project configuration for each assistant. An override that refers to an unselected provider stops before changes. Codex global MCP remains a preview: `ws connect codex --write` is a separate explicit choice. Setup does not link user-level skills. Restart/trust the workspace; doctor shows the chosen preset. `ws connect copilot` targets Copilot CLI rules plus project MCP, without lifecycle capture; `ws connect vscode` remains the separate VS Code Local-hook adapter.
