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

Claude Stop and PreCompact hooks capture cue-bearing decisions and the latest assistant summary from Claude transcripts only. Captures are redacted, appended and unverified; use `/handoff` for precise notes. [Decision-capture PR #11](https://github.com/Alenroyfeild/ai-dev-workspace/pull/11) remains under review.

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

`ws assist` offers at most two local suggestions and asks before applying. `ws assist decide <id> accepted|declined|snoozed|always [--until YYYY-MM-DD]` remembers permission in `.ws/assist.json`; declined hides it for 30 days. `ws assist apply <id>` runs only an accepted/always map or trace action. Other commands stay for review. Notices offer suggestions once, at most two total. Daily Codeburn cache data guides cost advice; protected built-ins, the workspace server, Graphy tools, in-use servers and tools pinned `on` are excluded. It never runs `codeburn optimize --apply`. [Assist PR #14](https://github.com/Alenroyfeild/ai-dev-workspace/pull/14) and [tool profiles/cost PR #16](https://github.com/Alenroyfeild/ai-dev-workspace/pull/16) are pending review. Configure `tool_profile` as `lean` (core only), `standard` (recommended tools) or `full`; `tool_overrides` maps tool names to `on`, `off` or `ask`. These settings guide assist and doctor and never remove software.
`ws run import codeburn [--since YYYY-MM-DD] [--task ID]` imports local `codeburn.export.v2` records. Matches use canonical repo paths and task windows; ambiguous records are skipped. Input totals include cache reads/writes; reasoning tokens are not counted again. Re-importing a grown session updates its existing entry (task/session/provider/model key); task text stays unchanged, and run logs retain no raw exports or project paths. Missing Codeburn prints its install command but never installs it. Codeburn defaults to 30 days; use `--since` for more. See [its export implementation](https://github.com/getagentseal/codeburn/blob/main/src/export.ts). [Import PR #15](https://github.com/Alenroyfeild/ai-dev-workspace/pull/15) and [update PR #17](https://github.com/Alenroyfeild/ai-dev-workspace/pull/17) are pending review.

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
