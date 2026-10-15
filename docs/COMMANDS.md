# Commands

Every command works from inside a workspace folder (or with `WS_ROOT` set). In a terminal they print plain lines; piped output is JSON, and `WS_JSON=1` forces JSON.

## Set up

| Command | Does |
|---|---|
| `ws init <dir> [--name N] [--repo R] [--pack P]` | Create a workspace named for its folder unless `--name` is supplied. Never overwrites your files: conflicts are written beside them as `.ws-new`. With `--repo`, also writes the codebase map. |
| `ws connect claude\|codex\|cursor\|vscode\|gemini` | Connect an assistant's project config (MCP, hooks). The kit skills (`/handoff`, `/pickup`, `/lesson` are already project-local) stay out of your global folders unless you add `--skills`, which links the extra ones (e.g. `/thinkbeforeact`) into `~/.claude/skills` or `~/.agents/skills`; existing names are kept. Codex: prints the config block; `--write` appends it with a backup. |
| `ws tools [--cost]` | List recommended, optional and caution tools; `--cost` reports MCP schema bytes, skill/plugin metadata size and cached Codeburn use over 30 days. |
| `ws doctor` | What is installed, which assistants are connected, what is missing under the active tool profile and overrides. |
| `ws packs` / `ws pack add <name>` / `ws pack add --from <dir>` / `ws pack remove <name>` | List packs, add a bundled or private local pack, and remove a private pack. Removal deletes only unchanged files that pack created; pre-existing or edited files are kept. Bundled packs are additive and are not removed by this command. |
| `ws map [<repo>]` | Rewrite the codebase map; link an existing `graphify-out/GRAPH_REPORT.md` and its top headings. `ws search` includes that report. The kit never runs Graphify. |

## Daily loop

Claude and Codex hooks can capture cue-bearing decisions and assistant summaries from supported transcripts. Captures are redacted, unverified and best-effort. Save important corrections explicitly with `ws remember`; use `/handoff` for progress notes.

| Command | Does |
|---|---|
| `ws task new <ID> "<title>"` / `find` / `list` / `show <ID> --section "Next action"` | Task records. `show --section` reads only what you need. |
| `ws task depend <ID> --on <OTHER>` | Make `<ID>` wait for `<OTHER>` (stored as `depends_on: A-1, A-2` in the task header). Both tasks must exist; self-dependencies and cycles are refused. |
| `ws next [--json]` | Open tasks (not done, not blocked) whose dependencies are all done, in_progress first, then review, ready, backlog. Each line: `ID status title (unblocks: X, Y)`, then `N waiting on dependencies`. |
| `ws task import <file> [--prefix SPEC] [--yes]` | Create tasks from a Task Master `tasks.json` (`tasks` list or `{"master": {"tasks": [...]}}`; subtasks are not imported) or a Spec Kit style `tasks.md` (`- [ ] T001 ...`, `- [x]` = done, optional `(depends on T001, T002)`). IDs become `SPEC-1` / `SPEC-T001`. Preview by default, `--yes` writes; existing IDs are skipped and reported, never overwritten; unknown dependencies or cycles block the write. Task Master `done` maps to done, `in-progress` to in_progress, `review`/`blocked` as is, `deferred`/`cancelled` to backlog, everything else to ready. |
| `ws claim <ID> [--worker W]` | Take the task as `$USER` unless `--worker` is supplied. The claim is remembered locally, so the next commands need no token. |
| `ws checkpoint <ID> --status <s> --next "<exact next step>" [--note "Evidence=..."]` | Save progress and the exact next step. |
| `ws release <ID>` | Give the task back. |
| `ws remember "<decision>" [--task ID]` | Save one decision (e.g. `"use Postgres, not SQLite"`) in your claimed task; the next session's brief lists it first. Secrets and `<private>` text are removed. |
| `ws brief` | Task memory in under 200 words, with separate section budgets: newest captured constraints and explicit decision lines first, then next action and blockers; long Handoff prose and matching lessons last. Explicit Handoff is labelled as saved task-record text, separate from unverified captures. `[truncated: see task record]` marks clipped or omitted context; read the task's sections for the full source. The brief cannot recover decisions missing from the saved record. Existing Copilot/Cursor native blocks receive the same brief on checkpoint or `ws brief --refresh`. The session-start hook also runs this; in Claude Code and Codex it also shows you one line (`Remembered: 3 decisions · next: ...`, or how to save memory when there is none) via the hook's `systemMessage`; other clients get the brief only. `Memory check` flags changed/undone code; unmatched lesson paths show `(paths gone)`, and more than three matches collapse to `Lessons: N more`. |
| `ws lesson add "<what happened → rule>"` / `ws lesson search "<words>"` | Lessons learned. |
| `ws search "<words>"` | Ranked snippets from the vault notes. |
| `ws sessions search "<words>"` | Search local Claude Code, Codex, Cursor and Gemini transcripts with read-only, redacted snippets. |
| `ws import native [--client claude\|codex\|gemini\|all] [--task ID] [--yes]` | Preview (max 20 redacted lines) memories the assistants saved natively. Claude: `~/.claude/projects/<folder>/memory/*.md` for the workspace and each configured repo folder. Codex: `stage1_outputs` rollout summaries in `$CODEX_HOME/memories_1.sqlite` whose slug or raw memory names the workspace or repo folder. Gemini CLI: the `## Gemini Added Memories` lines of `~/.gemini/GEMINI.md` (written by older `save_memory`/`/memory add`; current Gemini CLI docs say the agent edits memory Markdown files directly, including a private per-project folder whose format is undocumented, so newer entries are not imported). `--yes` appends one `### Imported <date> (unverified, from <client>)` block per client to the task Handoff (`--task`, else the single in-progress task): redacted, at most 150 words per client, skipped when already there. Native stores are only read. |
| `ws paste` | Save clipboard text (or piped stdin) redacted in `.ws/inbox/`, then print only its digest. |
| `ws digest <file> [--focus <regex>] [--local-summary]` | Show bounded context around matching lines first (bounded regex, scans the first 4096 characters per line), then the deterministic digest. `--local-summary` requires the `local-llm` pack. |

`ws connect` installs a prompt-size guard for Claude Code (`UserPromptSubmit`), Codex (`UserPromptSubmit`), Cursor (`beforeSubmitPrompt`) and Gemini CLI (`BeforeAgent`). Prompts over 150 lines or 12 KB are saved redacted in `.ws/inbox/` and blocked; send a short question with the relevant excerpt, or put `!raw` alone on the first line to bypass. These clients document blocking prompt hooks: [Claude Code](https://code.claude.com/docs/en/hooks), [Codex](https://learn.chatgpt.com/docs/hooks), [Cursor](https://cursor.com/docs/hooks), and [Gemini CLI](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md).

Toolbox levels: recommended tools are suggested for most workspaces, optional tools add specific capabilities, and caution tools can change routing or configuration. Nothing is installed automatically.

## Save a correction

After `ws start` has created and claimed your branch task, save a correction before
closing the session:

```bash
ws remember "Correction: store totals in integer cents; this replaces the earlier float decision."
ws brief
```

Check that the corrected decision appears in the brief. You can also ask your
assistant to save it with the MCP `remember` tool, then confirm with `ws brief`.
A chat correction alone is not a reliable saved record.

`ws remember` appends a decision; it keeps earlier notes. Say which earlier choice
the correction replaces, and review the task's Handoff if old notes conflict.
The saved decision survives a checkpoint, so use your usual `/handoff` or
`ws checkpoint` to record the next action too. With multiple claimed tasks, pass
`--task <ID>` to select the task you own.

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

`ws run log` accepts `--result ok|failed|rejected|accepted|skipped` (default `ok`), plus `--worker-role`, `--effort`, repeated `--check "<command>=<exit code>"`, `--files N`, `--verdict accepted|changes|rejected`, and `--findings N`. Counts must be nonnegative. Checks are caller-reported; commands are never executed. Records append to `vault/Runs/<task>.jsonl`; old records remain readable. Two consecutive steps on one task with failed/rejected results, changes/rejected verdicts, or nonzero check codes make `ws brief` and `ws nudge` warn: "stop: two failed attempts, re-diagnose before trying again". A later nonfailing step clears that task's warning; another task's steps do not. This is an advisory guard, not execution enforcement. Log actual token counts only when available; omitted counts retain the existing zero defaults.

The MCP server defaults to the **core** profile: `brief`, `remember`, `checkpoint`, `search_vault`, `find_task`, and `read_task`. `ws doctor` shows the MCP profile separately from the external tool catalog's `tool_profile`.

To enable more tools, edit your private workspace's `workspace.json`:

```json
{"mcp_tool_profile": "core", "mcp_tools": ["know_add", "search_sessions"]}
```

Set `"mcp_tool_profile": "full"` to restore all registered tools for an existing workflow. `mcp_tools` adds named tools to core; invalid names or profile values reject tool requests. Unselected tools cannot be called directly. Restart the client after changing this configuration so it refreshes its tool list. CLI commands, MCP prompts and resources keep their existing behavior. MCP `log_step` accepts the same metadata as `ws run log`; `trace` takes `task`. Setup, pack installation and feedback submission stay CLI-only.

Discovery and calls follow the [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).


### Select assistants

After `ws init`, run `ws setup` to choose assistants interactively, or `ws setup --assistants codex` / `ws setup --assistants claude,codex` / `ws setup --preset cursor-only`. `ws setup --detect` only checks CLI names on PATH and macOS app paths; it never launches clients or checks login. Other platforms have CLI detection and manual app selection.

Setup previews by default (`--dry-run` also works), reporting routing changes, configuration paths and trust steps. Review that output, then repeat with `--apply`. Apply backs up routing/workspace metadata in `.ws/backups/`, preserves user text and compatible overrides, and connects project configuration for each assistant. An override referring to an unselected provider stops before changes. `copilot` and `vscode` select the `copilot-only` provider preset and the VS Code Local connector; Copilot CLI lifecycle support is not implied. Codex global MCP stays a preview: `ws connect codex --write` is a separate explicit choice. Setup never links user-level skills. Restart/trust the project and approve MCP/hooks in each client; doctor shows the chosen preset, not verified login or model access.

### Link a private team repo (T1)

`ws team init <private-remote> --dry-run` previews a local team clone and metadata;
repeat without `--dry-run` to confirm. Create the empty private remote yourself;
init prepares an uncommitted `team.json` in `.ws/team`, never a push. Inspect it,
then use your normal Git commit/push flow to bootstrap that team repo.
Teammates use `ws team link <private-remote>`; repeat is status-only.
Privacy uses an installed `gh`/`glab`, or explicit `--attest-private` for that exact
remote when verification is unavailable. Known public/internal visibility blocks
linking. `--verify-with gh|glab` selects a verifier for a self-hosted remote.
`--yes` confirms the printed preview; use `--auto-pull` or `--no-auto-pull` to record
the pull preference noninteractively. Automatic pulls/scheduling are not active in
T1; publishing is never authorized by pull consent. Doctor labels verified versus
attested privacy. `ws team unlink` preserves `.ws/team` and all private records;
move the retained clone yourself before a new link. No installs or assistant runs.

### Local sharing scope (T2)

`ws scope task:<ID>` reads scope; `ws scope task:<ID> team` (or `private`) changes
only that record's frontmatter. `decision:`, `lesson:` and `knowledge:` select
standalone files in vault/Decisions, vault/Lessons and vault/Knowledge. Their flat
frontmatter must include `id: <ID>`; missing scope means private. Inline Handoff
decisions and legacy Learnings.md lines stay private; this command does not convert
them. New tasks explicitly start private. Notes, `.local.md` files and symlinked
records/directories are ineligible. Claimed tasks require the matching local claim.
`--expected-sha <sha>` protects changes after inspection. Record text outside the
frontmatter stays intact, including line endings. `share: ask` is the default
workspace policy and the only supported policy; category auto-publish rules are
not approved. Team scope is eligibility, never consent to copy, commit or push.
No Git operation or remote access occurs here; share/unshare arrives separately.
`ws start` creates `.codex/config.toml` only when absent, with the existing local undo record. If global Codex configuration already connects this workspace, start/doctor report connected and skip project config/manual paste. Otherwise existing project config is never parsed or edited: it prints the exact MCP block and destination, and start/doctor show **manual step pending**. Review and paste the block yourself; this status is conservative and remains pending. Legacy `ws connect codex --write` still explicitly edits global config with a backup. [Codex project config docs](https://learn.chatgpt.com/docs/config-file/config-basic).

## Selected team copies

`ws share task|decision|lesson|knowledge:<ID> [--dry-run] [--author alias]` previews the
redacted content, omissions, destination and diff, then asks once (`--yes` confirms
that preview). Select `scope: team` first with `ws scope`; scope alone never copies.
Task copies include Objective, Next action and Blockers; inline Handoff decisions
and automatic captures stay private. `ws remember --team`, `ws lesson add --team`
and `ws know add --team` create standalone records from only the selected text and
use the same gate. Declining retains the private save and standalone source.
`ws know add "text"` without `--team` saves private standalone knowledge.

`ws unshare <item>` previews removal of the local approved copy, keeps the private
original and warns that Git history and teammates' copies retain it. Changed or
conflicted copies, stale previews and symlink paths are refused. These commands
never commit, push or sync: copies remain local pending explicit Git publication.
The saved privacy consent must still match the linked team; remote visibility is
not re-queried by these local commands. Redaction is heuristic: inspect the preview.

`ws share <task-ID> --as runbook` requires `status: done` and `scope: team`. It uses
the same preview gate, redaction and source checks. Steps come from an optional
Steps section, otherwise saved Evidence and Checks; dead ends from Failures and
Do not redo; decisions/reasons from explicit Handoff `Decision:` / `Reason:` lines;
outcome from an optional Outcome section or Handoff `Outcome:` lines. Missing
details are labelled, never inferred. Raw Handoff prose and captures are excluded.
The private task is never changed. Runbooks and ordinary task copies have separate
receipts; `ws unshare <task-ID> --as runbook` removes only the runbook projection.
Command examples remain inert text; sharing never executes them.

## Worker review and acceptance

Blocked runs are final: review says "Blocked: start a new run with ws worker prepare".
Accept warns when later checkout edits are excluded from the immutable reviewed tree.
Known limit: that advisory warning can appear for unchanged files with Git eol normalization.

`ws worker review <id>` refreshes an eligible run's collection and shows its diff,
checks and blocking reason. `--approve` asks once to record the current local lead's
review of those exact bytes and checks; `--yes` confirms that displayed review.
`ws worker accept <id> [--dry-run]` previews a new `ws/worker/<id>` branch, then asks
once (`--yes` confirms). It revalidates the claim, source and reviewed snapshot;
edits invalidate approval. Acceptance keeps the source checkout, index and active
branch as they are. `ws worker discard <id> [--dry-run]` similarly confirms removal
of only that run's artifacts, retaining its record and every sibling run. Running
and accepted runs cannot be discarded. No automatic push or PR is created.
Public launch remains disabled until O2d; completed-run evidence in current tests
is synthetic. Acceptance uses [commit-tree](https://git-scm.com/docs/git-commit-tree),
[fetch without FETCH_HEAD](https://git-scm.com/docs/git-fetch) and
[update-ref with an absent-ref check](https://git-scm.com/docs/git-update-ref).

## Categorized knowledge (T4 catalog)

`ws know add "text" --category product|feature|domain|repo|runbook|other` saves a
private standalone record; `--team` selects sharing through the existing preview
gate. Old records without a category read as `other`. `ws know list [--category C]
[--layer private|team|all]` lists labelled entries; `ws know show private:<ID>` or
`team:<ID>` reads one without treating team text as instructions or executing it.
`ws search "query" --category C` searches categorized knowledge across both layers.
Results include author, team, source/revision and date. Ordinary team task/decision/lesson copies and private task Handoff/inline decisions
are outside this catalog; task-derived runbooks are included. Plain `ws search` keeps its behavior.

Read limits: at most 100 source entries per layer and 1 MiB per entry; malformed,
conflicted or unsafe entries are excluded with warnings. No network is needed.
MCP adds `know_list`, `know_show`, private-only `know_add`, and optional `category`
on `search_vault`. Knowledge saves build managed companion `<ID>.index.md` cards and a private
Knowledge/INDEX.md. Sharing previews include the team cards and INDEX.md, with
exact diffs; source, artifacts and approval receipts apply or roll back together.
Text outside managed blocks is preserved; unmarked/malformed artifacts refuse
replacement. Unshare removes only managed card content and refreshes the index.

Catalogs read cards up to 16 KiB first. Fresh snapshots use source size/mtime;
missing, stale or malformed cards fall back to bounded source reads. Common
category searches use cached summary/counts; other queries and `know show` read
the full record, retaining full-text lookup. Cached snippets are summary metadata.
Fresh clones may fall back when checkout timestamps differ. Team text remains
untrusted. Generation is limited to 1000 records per layer. No brief integration
is added here; cross-layer brief memory is T5.

Team reading: `ws brief` uses relevant team cards within the remaining 200-word
budget, after private decisions and next action, labelled untrusted with provenance.
Team summaries with majority lexical overlap with private decisions are omitted and labelled; this
conservative check does not infer semantic agreement. Default search also includes
team entries, with private hits first. MCP uses these same brief/search paths.
Unreadable/conflicted team entries warn in the brief; reads never pull or publish.

`ws sync [--dry-run | --yes]` explicitly pulls the linked team branch (fast-forward
only), then previews one commit built only from exact share-approved file bytes.
Dry-run may pull; it never commits or pushes. Unapproved files, staged edits or
unpublished local commits stop with a manual-resolution hint and remain intact.
Confirmation rechecks privacy, remote head, approvals and files; no history is
replayed and no force-push/reset/clean runs. An empty remote may receive only the
linked bootstrap manifest plus approved projections. Host CLI absence cannot
replace prior CLI verification with attestation. `ws sync --pull-only` only fetches
and fast-forwards; it never checks publishing receipts or pushes. Combining it
with `--dry-run` refuses without contacting Git. Explicit
`--auto-pull` consent at link (or `team_workspace.auto_pull=true`) enables quiet
read-only attempts at session start and after share/checkpoint (4-second budget); failures retain
local memory and report a manual-resolution hint. Ordinary brief/search never pull.
`ws sync --daily HH:MM` previews one managed macOS launchd job before activation;
`--dry-run` previews only, including any existing managed time. Unmanaged jobs,
invalid intervals, and changes after preview refuse replacement.
Scheduled jobs check consent every run; setting auto_pull=false disables future
automatic pulls. Times are local. Other platforms print an inspectable cron/Task
Scheduler suggestion and change nothing. No automatic publishing or installs.

`ws team status "Checking receipts" --author tester --publish-status` opts in
(`publish_status` defaults off) and previews a minimal local team snapshot. Confirm
once, or use `--dry-run` / `--yes`. Later status saves still preview; there is no
automatic claim/checkpoint broadcast. Only alias, task title, bounded one-line text
and date are saved; the task must be locally claimed. `ws team status` lists safe
snapshots; brief shows the two newest snapshots, labelled untrusted and last reported, never live availability.
`ws team status --author tester --disable-status` previews opt-out and removal of
that locally approved alias; Git history/other copies retain it. Copies changed by
others refuse overwrite. Transport is the separate T7a `ws sync`; this command
never commits or pushes, and works without an installed assistant.


`ws team link /path/to/shared-folder --folder --attest-private` previews an
existing team folder and copies a validated snapshot into `.ws/team`; it never
writes the source folder. Attestation binds the canonical folder, filesystem
identity and team manifest. User-selected aliases resolve at link; internal symlinks
remain refused. Sync metadata (`Icon\r`, `.DS_Store`, `.dropbox`, `.dropbox.attr`) is
skipped; iCloud placeholders stop with a Finder/Keep Downloaded hint.
The folder must contain `team.json` plus complete
entry/card pairs; unexpected/conflict-copy files or partial cards stop the pull
and retain the previous snapshot for manual recovery. `ws sync --pull-only`
refreshes only an unedited mirror; pending local changes are preserved and stop
refresh. Reads use the last local snapshot offline. `ws team init <existing-empty-folder> --folder --attest-private` previews one
new manifest and the local link; it never replaces an existing manifest. If the
manifest is created but linking fails, both copies remain for manual recovery.
POSIX creation uses the attested directory descriptor, even if its pathname is
replaced. Windows checks identity before and after each write and reports the
written path on a mismatch; concurrent replacement of the team folder by another
local process is outside the trust boundary on Windows.
Folder publication remains a separate step. No sync client is configured,
installed or contacted by ws; cloud delivery and cross-device atomicity are not
proved. Unlink keeps the local mirror and source folder.

Team saves (`ws remember --team`, `ws lesson add --team`, `ws know add --team`, and `ws share`) accept `--author <alias>`. The default is Git `user.name` with non-portable characters replaced by `-`, capped at 40 characters (`local` when unavailable). Review that alias in the existing sharing preview before approving; use an override to avoid sharing your Git name. Briefs show a compact untrusted author/date label; `ws know show team:<ID>` retains full provenance.
