# Commands

Most commands run from inside a workspace folder, or with `WS_ROOT` set. `ws demo`, `ws start`, `ws init`, `ws audit` and `ws doctor` work without one. In a terminal, commands print plain lines. Piped output is JSON; `WS_JSON=1` forces JSON. `ws --workspace-root DIR <command>` points one command at a workspace explicitly (hooks use it), `ws --version` prints the version, and `ws help` or `ws help all` lists the daily or every command.

Sections: [Daily use](#daily-use), [Tasks and checkpoints](#tasks-and-checkpoints), [Search and lessons](#search-and-lessons), [Team sharing](#team-sharing), [Setup and assistants](#setup-and-assistants), [Packs](#packs), [Maintenance and upgrades](#maintenance-and-upgrades), [Advanced and experimental](#advanced-and-experimental).

## Daily use

| Command | What it does |
|---|---|
| `ws start [--dry-run] [--yes] [--workspace DIR] [--undo] [--memory-dir DIR] [--no-import]` | In a code repo, connect it to private memory outside the checkout (default `~/.ai-dev-workspace/<repo-name>`). Previews first; `--yes` applies without prompting. `--undo` removes unchanged repo wiring and keeps your private memory. `--memory-dir` and `--no-import` control the memory import (see Import existing memory). |
| `ws demo` | Try remembered decisions in a throwaway workspace, from any folder, with no assistant or network: saves a sample decision, reads its brief in a fresh process, then removes the demo files. Your own workspace and assistant settings are not touched. |
| `ws brief` | Print task memory in under 200 words: decisions, next action, blockers, matching lessons. The session-start hook runs it for you. |
| `ws remember "<decision>" [--task ID]` | Save one decision (for example `"use Postgres, not SQLite"`) in your claimed task. The next brief lists it first. Secrets and `<private>` text are removed. |
| `ws nudge` | Print the checkpoint reminder for unrecorded work. The Stop and pre-compact hooks run it (`--hook`, `--client` as for `ws brief`). |
| `ws status` | Workspace overview. `--text` gives a readable summary. |
| `ws audit [repo] [--text]` | Score a repo's AI assistant setup (instruction files and size, references to missing files, memory, hooks, MCP server count, stale tasks) and list the top 3 fixes. Read-only, offline, safe to paste. `--text` forces the readable summary. |
| `ws doctor` | Show what is installed, which assistants are connected and what is missing. `--mcp` runs the MCP connection checks. |

Details:

- Restart the assistant session after `ws start --undo` or `ws team unlink`. A running session keeps its MCP server.
- Claude and Codex hooks can capture decisions and summaries that carry a cue word. Captures are redacted, unverified and best-effort. Save important corrections with `ws remember`, and use `/handoff` for progress notes.
- `ws brief` lists newest captured constraints and explicit decisions first, then next action and blockers, then long Handoff prose and matching lessons. `[truncated: see task record]` marks clipped context; read the task's sections for the full text. It cannot recover decisions missing from the saved record.
- `Memory check` flags changed or undone code. Lesson paths that match nothing show `(paths gone)`; more than three matches collapse to `Lessons: N more`.
- `ws brief --refresh` (and every checkpoint) updates existing Copilot and Cursor native blocks. `ws brief` and `ws nudge` also accept `--client claude|codex|cursor|gemini|vscode` and `--hook` (read hook input on stdin).
- In Claude Code and Codex, the session-start hook also shows one line, for example `Remembered: 3 decisions · next: ...`, or how to save memory when there is none. Other clients get the brief only.
- `ws status` and `ws doctor` show `Codex goals: N active, M complete` for Codex goals that mention an in-progress task. `ws checkpoint --status done` hints while one is still active. Read-only; close goals in Codex.
- `ws start` creates `.codex/config.toml` only when absent, with a local undo record. If global Codex config already connects this workspace, start and doctor report "connected". Otherwise an existing project config is never parsed or edited: start prints the MCP block and destination, and start and doctor show **manual step pending** until you paste it yourself. `ws connect codex --write` still edits global config, with a backup. See the [Codex config docs](https://learn.chatgpt.com/docs/config-file/config-basic).

A newly linked teammate's brief includes one recent product, domain and repo knowledge card, labelled untrusted, until their selected task has a saved next action or task memory. These summaries fit the existing 200-word budget; saved private decisions still take precedence. Use `ws know list --layer team` for the catalog.

### Save a correction

After `ws start` has created and claimed your branch task, save a correction before you close the session:

```bash
ws remember "Correction: store totals in integer cents; this replaces the earlier float decision."
ws brief
```

Check that the corrected decision appears in the brief. You can also ask your assistant to save it with the MCP `remember` tool, then confirm with `ws brief`. A correction made only in chat is not a reliable saved record.

- `ws remember` appends and keeps earlier notes. Say which earlier choice the correction replaces, and review the task's Handoff if old notes conflict.
- The decision survives a checkpoint. Use `/handoff` or `ws checkpoint` to record the next action too.
- With several claimed tasks, pass `--task <ID>`.

## Tasks and checkpoints

| Command | What it does |
|---|---|
| `ws task new <ID> "<title>" [--objective T] [--branch B] [--repo R]` | Create a task record. |
| `ws task find <ref>` / `ws task list` / `ws task show <ID> --section "Next action"` | Find, list or read tasks. `--section` (repeatable) reads only what you need. |
| `ws task depend <ID> --on <OTHER>` | Make `<ID>` wait for `<OTHER>`. |
| `ws task import <file> [--prefix SPEC] [--yes]` | Create tasks from a Task Master `tasks.json` or a Spec Kit style `tasks.md`. Previews unless you pass `--yes`. |
| `ws next [--json]` | List open tasks that are ready to work on. |
| `ws claim <ID> [--worker W]` | Take a task as `$USER`, or as `--worker`. |
| `ws checkpoint <ID> --status <s> --next "<exact next step>" [--note "Section=text"]` | Save status and the exact next step. Status: `backlog`, `ready`, `in_progress`, `review`, `blocked`, `done`. `--note` is repeatable; `ws checkpoint --help` lists valid sections. |
| `ws release <ID>` | Give the task back. |
| `ws pr-notes [ID] [--no-link] [--json]` | Print the task as Markdown for a pull request, for example `gh pr create --body "$(ws pr-notes)"`. |
| `ws recap [--since 7d\|YYYY-MM-DD] [--json]` | Summarise tasks changed in a period (default `7d`), for standups and handoffs. |
| `ws validate` | Check task records, links and secrets. |

Details:

- `ws task depend` stores `depends_on: A-1, A-2` in the task header. Both tasks must exist; self-dependencies and cycles are refused.
- `ws next` lists tasks that are not done or blocked and whose dependencies are all done: in_progress first, then review, ready, backlog. Each line is `ID status title (unblocks: X, Y)`, then `N waiting on dependencies`.
- `ws task import` reads Task Master files as `tasks` or `{"master": {"tasks": [...]}}` (subtasks are not imported), or Spec Kit lines like `- [ ] T001 ...` (`- [x]` = done, optional `(depends on T001, T002)`). IDs become `SPEC-1` or `SPEC-T001`. Existing IDs are skipped and reported, never overwritten; unknown dependencies or cycles block the write.
- Task Master status mapping: `done` to done, `in-progress` to in_progress, `review` and `blocked` unchanged, `deferred` and `cancelled` to backlog, anything else to ready.
- The claim is remembered locally, so later commands need no token. `ws release` also accepts `--worker` and `--token`; `ws checkpoint` accepts `--worker`, `--token` and `--expected-sha` (refuse if the record changed since you read it).
- `ws pr-notes` includes goal, saved decisions with reasons, tried-and-rejected approaches (`Failures`, `Do not redo`), acceptance criteria, checks and open items. It leaves out unverified captures, template placeholders, secrets, `<private>` text and home paths, and adds a one-line credit link unless `--no-link`. It only prints; it never edits the task or calls GitHub.
- `ws recap` lists done tasks first, then review, in progress and blocked, with saved decisions and next action, plus teammates' shared notes and status when a team is linked. It is read-only and leaves out unverified captures, secrets, `<private>` text and home paths.

## Search and lessons

| Command | What it does |
|---|---|
| `ws search "<words>" [--category C]` | Ranked snippets from the vault notes. Team entries are included, private hits first. |
| `ws lesson add "<what happened -> rule>" [--tag T] [--path GLOB] [--area A] [--team]` | Save a lesson. `--tag` and `--path` are repeatable. |
| `ws lesson search ["<words>"]` | Search lessons. Without words, lists all of them. |
| `ws know add "text" [--category C] [--team]` | Save a standalone knowledge note. Categories: `product`, `feature`, `domain`, `repo`, `runbook`, `other` (default). Private unless `--team`. |
| `ws know list [--category C] [--layer private\|team\|all]` | List knowledge entries (default layer `all`). |
| `ws know show private:<ID>` / `team:<ID>` | Read one entry. Team text is data and is never executed. |
| `ws sessions search "<words>" [--root CLIENT=DIR]` | Search local Claude Code, Codex, Cursor and Gemini transcripts (redacted, read-only). `--root` uses explicit directories instead of the defaults. |
| `ws import native [--client claude\|codex\|gemini\|all] [--task ID] [--yes]` | Preview memories your assistants saved natively (default client `all`). `--yes` copies them into the task Handoff. |
| `ws paste` | Save clipboard text (or piped stdin), redacted, in `.ws/inbox/` and print only its digest. |
| `ws digest <file> [--focus REGEX] [--local-summary]` | Show a bounded digest of a big log or JSON file. `--focus` shows matching lines first. |

Details:

- Records saved before categories existed read as `other`. Team task, decision and lesson copies and private Handoff decisions are not in the knowledge catalog; task-derived runbooks are. `ws search --category C` searches categorized knowledge across both layers and shows author, team, source, revision and date.
- Limits: 100 entries per layer, 1 MiB per entry, 1000 generated records per layer. Malformed, conflicted or unsafe entries are skipped with warnings. No network is needed.
- Each knowledge save builds a managed `<ID>.index.md` card and a private `Knowledge/INDEX.md`. Sharing previews show the team cards and index with exact diffs; source, cards and approval receipts apply or roll back together. Text outside managed blocks is kept. Unshare removes only managed card content.
- `ws brief` adds relevant team cards after private decisions and next action, labelled untrusted with provenance. Team summaries that mostly repeat a private decision are omitted (a lexical check). Unreadable or conflicted team entries warn. Reads never pull or publish.
- `ws import native` previews at most 20 redacted lines. Sources: Claude `~/.claude/projects/<folder>/memory/*.md` (workspace and each repo folder); Codex `stage1_outputs` summaries in `$CODEX_HOME/memories_1.sqlite` that name the workspace or repo folder; Gemini CLI `## Gemini Added Memories` lines in `~/.gemini/GEMINI.md` (newer per-project Gemini memory files are not imported).
- `--yes` appends one `### Imported <date> (unverified, from <client>)` block per client to the task Handoff (`--task`, else the single in-progress task): redacted, at most 150 words, skipped if already there. Native stores are only read.
- `ws digest` scans the first 4096 characters per line with a bounded regex. `--local-summary` needs the `local-llm` pack.
- Prompt-size guard: `ws connect` installs a hook for Claude Code (`UserPromptSubmit`), Codex (`UserPromptSubmit`), Cursor (`beforeSubmitPrompt`) and Gemini CLI (`BeforeAgent`). Prompts over 150 lines or 12 KB are saved redacted in `.ws/inbox/` and blocked. Send a short question with the excerpt, or put `!raw` alone on the first line to bypass. Hook docs: [Claude Code](https://code.claude.com/docs/en/hooks), [Codex](https://learn.chatgpt.com/docs/hooks), [Cursor](https://cursor.com/docs/hooks), [Gemini CLI](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md).

## Team sharing

Nothing is shared automatically. Every step previews first. Only a confirmed `ws sync` pushes, and only records you approved for sharing.

| Command | What it does |
|---|---|
| `ws team init <private-remote> [--dry-run] [--yes]` | Preview, then create, a local team clone and metadata. |
| `ws team link <private-remote>` | Link to an existing team repo. Running it again only shows status. |
| `ws team unlink` | Unlink. Keeps `.ws/team` and all private records. |
| `ws team status "<text>" --author A --publish-status` | Opt in to team status snapshots. Later saves still preview. |
| `ws team status` | List safe team status snapshots. |
| `ws team status --author A --disable-status` | Preview opting out and removing your alias's snapshot. |
| `ws scope <item> [team\|private] [--expected-sha SHA]` | Read, or change, whether a record may be shared. |
| `ws share <item> [--dry-run] [--yes] [--author A] [--as runbook]` | Preview a redacted team copy, then ask once. |
| `ws unshare <item> [--dry-run] [--yes] [--as runbook]` | Preview removing the local approved copy. |
| `ws remember --team` / `ws lesson add --team` / `ws know add --team` | Save one item and share it through the same preview. |
| `ws sync [--dry-run \| --yes \| --pull-only \| --daily HH:MM]` | Pull team updates, then preview (and once confirmed, push) a commit of approved records only. |

`<item>` is `task:<ID>`, `decision:<ID>`, `lesson:<ID>` or `knowledge:<ID>`.

### Link a private team repo

- Create the empty private remote yourself. `ws team init <private-remote> --dry-run` previews; repeat without `--dry-run` to confirm. Init prepares an uncommitted `team.json` in `.ws/team` and never pushes. Run `ws sync` to publish it (it shows what it will push first); teammates can link only after that. At a terminal, team previews print a short summary (`+ <category> <text>` per note, the full text up to 600 characters, the destination, then `[y/N]`); piped or scripted runs get the full JSON, and `WS_JSON=1` forces it.
- Teammates run `ws team link <private-remote>`.
- Privacy is checked with an installed `gh` or `glab`, or with `--attest-private` for that exact remote when verification is unavailable. A remote known to be public or internal blocks linking. `--verify-with gh|glab` picks the verifier for a self-hosted remote. Doctor shows verified versus attested privacy.
- `--yes` confirms the printed preview. `--auto-pull` or `--no-auto-pull` records the pull preference without prompting. Pull consent never authorizes publishing.
- `ws team unlink` keeps the clone; move it yourself before a new link.

### Link a shared folder

- `ws team link /path/to/shared-folder --folder --attest-private` previews an existing folder, then copies a validated snapshot into `.ws/team`. It never writes to the source folder. Symlinks inside it are refused, and sync metadata (`Icon\r`, `.DS_Store`, `.dropbox`, `.dropbox.attr`) is skipped. iCloud placeholders stop with a Finder "Keep Downloaded" hint.
- The folder must contain `team.json` plus complete entry/card pairs. Unexpected or conflict-copy files and partial cards stop the pull and keep the previous snapshot.
- `ws sync --pull-only` refreshes only an unedited mirror; pending local changes stop it and are kept. Reads use the last local snapshot offline.
- Folder hosts ignore a shared `INDEX.md` and never write it. Link and pull build a private index at `.ws/team-index.md` from validated entry/card pairs; an older imported `.ws/team/INDEX.md` and text outside the managed markers are kept. Git-hosted teams keep their shared index.
- `ws team init <existing-empty-folder> --folder --attest-private` previews a new manifest and the local link, and never replaces an existing manifest. If linking fails afterwards, both copies stay for manual recovery.
- `ws share` stages only approved portable copies in the local mirror. Preview `ws sync`, then confirm to publish them to the attested folder. Each attempt saves raw source copies in `.ws/backups/folder-*/state.json`; conflicts stop, partial failures keep the backup and local approvals, and a completed publication with a failed local refresh is reported explicitly for retry. Automatic pulls never publish.
- Folder publication is limited to receipt-owned entry/card files and the publisher's own status file; the shared `INDEX.md` is never written. Two devices publishing the same owner's projection at once can race. Private originals stay intact: reconcile the retained copies, then publish the owner's original again.
- `ws` never configures, installs or contacts a sync client, so cloud delivery and cross-device atomicity are not guaranteed. Unlink keeps the local mirror and source folder.
- On Windows, another local process replacing the team folder is outside the trust boundary.

### Choose what can be shared

- `ws scope task:<ID>` reads the scope; `ws scope task:<ID> team` (or `private`) changes only that record's frontmatter. `decision:`, `lesson:` and `knowledge:` select standalone files in `vault/Decisions`, `vault/Lessons` and `vault/Knowledge`; their flat frontmatter must include `id: <ID>`.
- Missing scope means private; new tasks start private. Inline Handoff decisions and legacy `Learnings.md` lines stay private and are not converted.
- Notes, `.local.md` files and symlinked records or directories are not eligible. A claimed task needs the matching local claim.
- `--expected-sha` refuses the change if the record changed after you inspected it. Text outside the frontmatter is untouched.
- `share: ask` is the only supported policy; automatic publishing rules are not supported.
- Team scope means eligible, never consent to copy, commit or push. `ws scope` does no Git or remote access.

### Share and unshare

- `ws share` previews the redacted content, omissions, destination and diff, then asks once; `--yes` confirms that preview. Set `scope: team` first; scope alone never copies.
- Task copies include Objective, Next action and Blockers. Inline Handoff decisions and automatic captures stay private.
- The `--team` saves create standalone records from only the selected text. If you decline, the private save stays. `ws know add "text"` without `--team` saves private knowledge.
- `ws unshare` keeps your private original and warns that Git history and teammates' copies retain the shared text. Changed or conflicted copies, stale previews and symlink paths are refused.
- These commands never commit, push or sync; copies stay local until you publish through Git. Saved privacy consent must still match the linked team, and remote visibility is not re-checked. Redaction is heuristic: read the preview.
- `--author <alias>` sets the shared author. The default is Git `user.name` with non-portable characters replaced by `-`, capped at 40 characters (`local` if unavailable). Check it in the preview, and override it to avoid sharing your Git name. Briefs show a compact, untrusted author and date label; `ws know show team:<ID>` shows full provenance.

#### Share a finished task as a runbook

`ws share <task-ID> --as runbook` needs `status: done` and `scope: team`, and uses the same preview, redaction and source checks.

- Steps come from an optional Steps section, otherwise saved Evidence and Checks. Dead ends come from Failures and Do not redo.
- Decisions and reasons come from explicit Handoff `Decision:` and `Reason:` lines. The outcome comes from an Outcome section or Handoff `Outcome:` lines.
- Missing details are labelled, never inferred. Raw Handoff prose and captures are excluded.
- The private task is never changed. Runbooks and ordinary task copies have separate receipts; `ws unshare <task-ID> --as runbook` removes only the runbook copy.
- Command examples stay inert text. Sharing never runs them.

### Sync and status

- `ws sync` pulls the linked team branch (fast-forward only) and prints a one-line count of notes pulled and published (to stderr), then previews one commit built only from share-approved file bytes. `--dry-run` may pull but never commits or pushes. `--yes` confirms the exact preview and rechecks privacy, remote head, approvals and files. No force-push, reset or clean ever runs.
- Unapproved files, staged edits or unpublished local commits stop the sync with a hint and stay intact. An empty remote receives only the bootstrap manifest plus approved copies.
- `ws sync --pull-only` only fetches and fast-forwards; it never checks publishing receipts or pushes. With `--dry-run` it refuses without contacting Git.
- Auto-pull: explicit `--auto-pull` consent at link (or `team_workspace.auto_pull=true`) allows quiet read-only pulls at session start and after share or checkpoint (4-second budget). A failure keeps local memory and prints a hint. `ws brief` and `ws search` never pull. `auto_pull=false` stops future automatic pulls.
- `ws sync --daily HH:MM` previews one managed macOS launchd job (local time) before activating it. `--dry-run` previews only, including any existing managed time. Unmanaged jobs, invalid intervals and changes made after the preview refuse replacement. Other platforms print a cron or Task Scheduler suggestion and change nothing. Each run rechecks consent. Nothing is published or installed automatically.
- `ws team status` saves only alias, task title, a bounded one-line text and the date, for a task you have claimed. `publish_status` defaults to off, and nothing is broadcast on claim or checkpoint. Confirm once, or use `--dry-run` / `--yes`. The brief shows the two newest snapshots, labelled untrusted and last reported, never live availability.
- `--disable-status` previews removing that alias's approved copy. Git history and other copies keep it, and copies changed by others are not overwritten. Use `ws sync` to move approved records.

## Setup and assistants

| Command | What it does |
|---|---|
| `ws init <dir> [--name N] [--repo R] [--pack P]` | Create a workspace. `--repo` and `--pack` are repeatable. |
| `ws setup [--assistants a,b] [--preset NAME] [--detect] [--dry-run \| --apply]` | Choose assistants and configure project connections. Previews unless you pass `--apply`. |
| `ws connect claude\|codex\|cursor\|copilot\|vscode\|gemini [--write] [--skills]` | Connect one assistant's project config (MCP, hooks). |
| `ws map [<repo>]` | Rewrite the codebase map. |
| `ws tools [--cost]` | List recommended, optional and caution tools. |

Details:

- `ws init` names the workspace after its folder unless you pass `--name`. It never overwrites your files; conflicts are written beside them as `.ws-new`. With `--repo`, it also writes the codebase map.
- `ws connect` keeps `/handoff`, `/pickup` and `/lesson` project-local. `--skills` also links the extra kit skills (for example `/thinkbeforeact`) into `~/.claude/skills` or `~/.agents/skills`, and existing names are kept. Codex: `ws connect codex` prints the config block and `--write` appends it with a backup.
- `ws map` links an existing `graphify-out/GRAPH_REPORT.md` and its top headings. `ws search` includes that report. The kit never runs Graphify.
- `ws tools --cost` reports MCP schema bytes, skill and plugin metadata size, and cached Codeburn use over 30 days.
- `ws tools` levels: recommended (most workspaces), optional (specific capabilities) and caution (can change routing or configuration). Nothing is installed automatically.

### Select assistants

After `ws init`, run `ws setup` to choose assistants interactively, or use `ws setup --assistants codex`, `ws setup --assistants claude,codex` or `ws setup --preset cursor-only`.

- `ws setup --detect` only checks CLI names on PATH and macOS app paths. It never launches a client or checks login. Other platforms have CLI detection and manual app selection.
- Setup previews by default (`--dry-run` also works) and reports routing changes, config paths and trust steps. Review it, then repeat with `--apply`.
- Apply backs up routing and workspace metadata in `.ws/backups/`, keeps your text and compatible overrides, and connects project config for each assistant. An override for an unselected provider stops before any change.
- `copilot` and `vscode` select the `copilot-only` provider preset and the VS Code local connector. Copilot CLI lifecycle support is not implied.
- Codex global MCP stays a preview; `ws connect codex --write` is a separate choice.
- Setup never links user-level skills. Restart or trust the project and approve MCP and hooks in each client. Doctor shows the chosen preset, not verified login or model access.

### Import existing memory

On first `ws start`, the setup preview includes private copies of `CLAUDE.md`, `.claude/CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.cursor/rules/*.mdc`, and Markdown from the standard repo-specific Claude auto-memory directory. The preview shows each source label, redacted UTF-8 byte size and first line (at most 80 characters); `--dry-run` shows the full redacted text without writing. One confirmation approves the displayed setup and source copies; `--yes` approves the same preview for scripts. Use `--no-import` to connect without copying memory. For custom Claude storage or a Git worktree, pass `--memory-dir <directory>` (find it with Claude's `/memory`).

Import reads bounded regular files only (16 KiB each, 64 KiB total, at most 16 Cursor rules and 16 Claude memory files; excess file counts are reported); unsafe, unreadable or oversized files are skipped. It redacts known secrets and private markers, follows no symlinks or `@` imports, and never executes source instructions. Copies have private scope in the workspace's `vault/Knowledge/`; a bounded, **unverified context** excerpt appears after saved decisions in the task brief. `AGENTS.md` is kept for private knowledge/search but omitted from that excerpt because both clients already read it natively. Imported text is not a new user-stated decision or permission to act. Originals remain unchanged. Repeating start shows status; undo removes repo wiring and keeps private memory. Re-setup avoids duplicate copies of unchanged sources. Read the private knowledge records for full copies.

Claude's [memory documentation](https://code.claude.com/docs/en/memory#storage-location) describes the standard per-repository auto-memory directory and custom storage. This importer does not parse Claude settings or recursively follow its memory index.

## Packs

| Command | What it does |
|---|---|
| `ws packs` | List available packs. |
| `ws pack add <name>` | Add a bundled pack. |
| `ws pack add --from <dir>` | Add a private local pack. |
| `ws pack remove <name>` | Remove a private pack. |

Details:

- `ws pack remove <name>` deletes only unchanged files that the pack created. Pre-existing or edited files are kept.
- `ws guard --hook` and `ws discipline --hook [--client C]` are the hook entry points the opt-in `guards` and `discipline` packs install. They read hook JSON on stdin and are not meant to be run by hand.
- Bundled packs are additive and are not removed by this command.

## Maintenance and upgrades

| Command | What it does |
|---|---|
| `ws update [--check]` | Update the kit if it is a git clone, or print the pipx command for a pipx install. `--check` only looks. |
| `ws upgrade [--dry-run]` | Apply this kit version's managed workspace rules, hook handlers and Claude/Codex handoff, pickup and lesson skills. |
| `ws notices` | Show a new release, fixed issues and unshared feedback. Your assistant runs it once per session and asks before acting. |
| `ws feedback add "<text>" [--kind K] [--source S]` | Record feedback about the workspace. `--kind` defaults to `idea`, `--source` to `user`. |
| `ws feedback list [--all]` / `ws feedback sync` | List items, or tick items whose issue is closed. |
| `ws feedback submit N [--yes]` / `ws feedback link N <url>` | Turn item N into a GitHub issue after a redacted preview (`--yes` confirms it), or record its issue URL. |
| `ws version` | Print the kit version. |

Details:

- `ws upgrade --dry-run` previews exact managed-file diffs without writing. `ws upgrade` backs up changed files under `.ws/backups/<UTC timestamp>/`, adds managed routing defaults (keeping root overrides) and creates an empty claim directory. Existing claims are never changed.
- Managed Markdown blocks carry `ws:managed` markers with the kit version; managed hooks use `statusMessage: ws:managed:<event>:<kit version>`. Keep personal rules, settings and hooks outside them; their bytes are not changed.
- Unmarked or ambiguous files (including routing files) produce `.ws-new` proposals, numbered if an earlier one was edited. Adopt them by hand, then rerun the dry run.
- `workspace.json` records schema 2, kit version, a content fingerprint and pending proposals, and keeps custom keys and vault paths.
- No tools or global skills are installed. Clients ask you to review and trust changed hooks again.
- Symlink targets and newer schemas are refused. There is no MCP upgrade tool. Each write is atomic, but a multi-file upgrade is not one transaction.

## Advanced and experimental

| Command | What it does |
|---|---|
| `ws route [role] [--text]` | Show the configured binding for a role (default `lead`) and whether its CLI or model setting is available. |
| `ws delegate <task> --role <role> [--run]` | Prepare a redacted brief for a worker and print the exact command to run. |
| `ws delegate <task> --role reviewer --diff <range> [--run]` | Same, with a diff stat, changed files and bounded hunks. |
| `ws delegate --selftest [--provider codex\|claude]` | Try hostile writes against the explorer worker in a throwaway tree and report whether the disk changed. History, not a security guarantee. |
| `ws worker prepare <task> --scope S [--base REF] [--dry-run] [--yes]` | Prepare an isolated implementation checkout. `--scope` is required and repeatable; `--base` defaults to `HEAD`. |
| `ws worker review <id> [--approve] [--yes]` | Show a run's diff, checks and blocking reason, or record your review. |
| `ws worker accept <id> [--dry-run] [--yes]` | Preview, then create, a `ws/worker/<id>` branch from the reviewed run. |
| `ws worker discard <id> [--dry-run] [--yes]` | Remove one run's artifacts. |
| `ws worker launch <id>` | Gated and disabled for now. |
| `ws run log <task> <step> --provider P [options]` | Log one step: who did what, tokens, seconds and result. |
| `ws run report [task]` | Report logged steps. |
| `ws run import codeburn [--since YYYY-MM-DD] [--task ID]` | Import local usage records from CodeBurn. |
| `ws trace <task>` | Print a read-only Markdown timeline with reported checks, verdicts and total tokens. Redirect stdout to save it. |

`ws assist` offers up to two local workspace suggestions and asks before applying. Use `ws assist apply <id>` or `ws assist decide <id> accepted|declined|snoozed|always [--until YYYY-MM-DD]` to act on one. Tool installation suggestions come only from the explicit `ws tools` catalog.

`ws run import codeburn` re-imports a grown session into its existing entry. Run logs omit raw exports and project paths. CodeBurn defaults to 30 days; `--since` widens it.

Routing, permission and cost settings: [ADVANCED.md](ADVANCED.md). `ws route` availability does not verify login or account access.

### Delegate

- `ws delegate` prepares a redacted brief of at most 400 words and prints the exact command. Only `explorer` and `reviewer` support `--run` (routing timeout, default 600 seconds); other roles are preparation-only.
- Workers are read-only. Codex runs with a read-only sandbox, no approvals, hooks, apps or plugins, and user config ignored. Claude uses project-only settings and only Read, Glob and Grep. Ollama is preparation-only. Allowed paths define prompt scope; they are not a read-access jail.
- Output stays UNVERIFIED in `.ws/briefs/`, a short summary is appended to Evidence, and `ws trace` records role, model, effort, time and result, never a review acceptance. The lead decides and reviews.
- MCP `route` and `delegate` only prepare and reject run arguments. There is no credential inspection, automatic dispatch or installation.
- `--diff` revisions must resolve to commits; a single revision compares against the working tree. Hunks may be truncated, so the reviewer can inspect the listed files. Diff content is redacted. MCP `delegate` accepts `diff` for preparation only.
- Reviewer output is one `UNVERIFIED file:line: problem. fix.` line per finding. `ws trace` counts distinct matching lines; the count is unverified, never an acceptance.
- `--selftest` runs the explorer in a new throwaway Git tree. Codex runs; Claude only prepares unless you pass `--run`. It reads a random token, then tries hostile writes (patch, shell, Python, absolute path, symlink, parent path, Git commit) and compares disk contents, modes, directory entries and times.
- Selftest exit codes: `SELFTEST OK` (0) needs a successful read and unchanged disk; `FAIL` (1) means something changed; `INCONCLUSIVE` (2) means the read or worker failed, or the run was preparation-only. Executed fixtures are removed; prepared ones stay for manual use. `.ws/delegate-selftests.json` keeps each provider's latest result for doctor. It is history, not a security guarantee or an execution gate.

### Workers

`ws worker launch` is disabled until a live Codex isolation check passes (Codex 0.155.1 still allows /tmp writes). Prepared runs can be reviewed, accepted or discarded.

- `ws worker review <id>` refreshes an eligible run and shows its diff, checks and blocking reason. A blocked run is final: start a new one with `ws worker prepare`.
- `--approve` asks once to record the lead's review of those exact bytes and checks; `--yes` confirms. Edits invalidate approval.
- `ws worker accept <id>` previews a new `ws/worker/<id>` branch, then asks once (`--yes` confirms). It revalidates the claim, source and reviewed snapshot, and leaves your checkout, index and active branch alone. It warns when later checkout edits are excluded from the reviewed tree (known limit: it can warn for unchanged files under Git eol normalization).
- `ws worker discard <id>` confirms, then removes only that run's artifacts and keeps its record and all other runs. Running and accepted runs cannot be discarded.
- No push or PR is created.

### Run logs

- `ws run log` takes `--result ok|failed|rejected|accepted|skipped` (default `ok`), `--model`, `--tokens-in N`, `--tokens-out N`, `--seconds N`, `--note`, `--worker-role`, `--effort`, `--files N`, `--verdict accepted|changes|rejected` and `--findings N`. Repeat `--check "<command>=<exit code>"` per check. Counts must not be negative.
- Checks are reported by you; commands are never executed. Records append to `vault/Runs/<task>.jsonl`. Log real token counts only when you have them; omitted counts stay zero.
- Two consecutive steps on one task with failed or rejected results, `changes` or `rejected` verdicts, or nonzero check codes make `ws brief` and `ws nudge` warn: "stop: two failed attempts, re-diagnose before trying again". A later nonfailing step on that task clears it. The guard is advisory.

### MCP tools

`mcp/server.py` lists 7 core tools by default (about 500 tokens instead of about 1,900): `brief`, `find_task`, `read_task`, `checkpoint`, `remember`, `search_vault` and `add_lesson`.

- Set `"mcp_tools": "all"` in `workspace.json` to list every tool, or give a list of names. Unlisted tools stay callable by name. `ws doctor` shows the profile.
- All 28: `know_list`, `know_show`, `know_add`, `route`, `delegate`, `assist`, `import_usage`, `search_sessions`, `codebase_map`, `brief`, `nudge`, `connect_client`, `find_task`, `read_task`, `new_task`, `claim_task`, `release_task`, `checkpoint`, `remember`, `search_vault`, `search_lessons`, `add_lesson`, `add_feedback`, `digest_file`, `log_step`, `trace`, `notices` and `status`.
- `search_vault` takes an optional `category`. `know_add` is private-only. `log_step` takes the same metadata as `ws run log` (`checks` is an array of `command=exit code` strings). `trace` takes `task`.
- Setup, pack installation and feedback submission are CLI-only on purpose.
