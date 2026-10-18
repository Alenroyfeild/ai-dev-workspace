# Changelog

## 0.1.0-beta.6 (unreleased)

### Fixed
- Native Claude memory with a UTF-8 BOM now imports its description correctly; BOM-only files are skipped as empty.
- Imported brief excerpts keep whole items and source IDs together.
- `ws brief` with no claimed task in a started repo now names the current branch's task and the exact `ws claim` or `ws task new` command to use. `ws start` and the SessionStart hook already resolve the same task for one repo and branch; a test now guards that.

### New
- Team previews at a terminal are a short summary (`+ category text`, destination, `[y/N]`) instead of raw JSON; `ws sync` prints a one-line pulled/published count; `ws know add` keeps a private note's `#private` text and paths as written (sharing it later still strips them) and says clearly when a `--team` note is entirely private; the team docs show the real quick-start order, the `#private`/`<private>` markers and a "rotate pushed secrets" warning.
- `ws start` previews existing project memory and copies approved text into private knowledge. The first brief includes imported context; originals stay untouched. Use `--no-import` to skip or `--memory-dir` for a custom Claude auto-memory directory.

### Fixed
- Team sync no longer stops when two teammates publish at once: the derived `INDEX.md` is rebuilt after the pull, so both entries are listed, and any remaining pull conflict names the file and the recovery command. A corrupt `team.json` now reports its path, shows in `ws doctor`, and no longer blocks `ws sync --pull-only` from pulling a teammate's fix.

### Improved
- Recent topic memories are imported first; Claude's `MEMORY.md` index is excluded from topic selection.

## 0.1.0-beta.5 (unreleased)

Team workspaces can now receive approved shared updates automatically or be read from a synced folder, while personal work stays private.

### New
- Start with team context: a new teammate's brief shows recent product, domain and repo knowledge cards before task-specific memory exists, within the usual brief budget and labelled untrusted. [Command guide](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/docs/COMMANDS.md#daily-loop).
- Try remembered decisions with `ws demo`: an offline, disposable walkthrough that saves a decision and reads it back in a fresh process, without starting an assistant. [Command guide](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/docs/COMMANDS.md#set-up).
- Consent to read-only team pulls at session start and after local shares or checkpoints. Publishing still uses the existing preview and approval flow.
- Schedule a confirmed daily team pull on macOS. Other platforms show setup suggestions without installing a scheduler.
- `ws pr-notes` prints the task's saved decisions, reasons, tried-and-rejected approaches, acceptance criteria and checks as a pull request description, so reviewers see why the code changed. Example: `gh pr create --body "$(ws pr-notes)"`.
- `ws recap` lists the tasks you changed this week with their decisions, tried-and-rejected approaches and next steps, plus teammates' shared notes, ready to paste into a standup or handoff. `--since 14d` or a date changes the period.
- Link an attested folder in a synced service and read a validated local snapshot offline. Folder links are read-only; publishing from them is not available yet.
- Team notes can show a chosen author alias and short label, so teammates can recognize who shared them.
- `ws audit` scores a repo's AI assistant setup (instructions and their size, broken file references, memory, hooks, MCP server count, stale tasks) and lists the top 3 fixes. Read-only and offline; the text output is safe to paste.
- Opt-in `guards` pack: `ws pack add guards`, then `ws start` again in your repo. Claude Code and Codex are then stopped before `rm -rf` on your home or the filesystem root, `git reset --hard`, force push, `git clean -f`, commands or file edits containing what looks like a secret, and edits that newly skip or narrow tests. Start the assistant with `WS_GUARDS=off` to turn it off for one session; `ws pack remove guards` and `ws start` remove the hook.
- Opt-in `guards` pack: `ws pack add guards`, then `ws start` again in your repo. Claude Code and Codex are then stopped (Windows PowerShell commands included) before `rm -rf` or `Remove-Item -Recurse -Force` on your home or the filesystem root, `git reset --hard`, force push, `git clean -f`, commands or file edits containing what looks like a secret, and edits that newly skip or narrow tests. Start the assistant with `WS_GUARDS=off` to turn it off for one session; `ws pack remove guards` and `ws start` remove the hook.
- Opt-in `discipline` pack (advisory, never blocks): after the same shell command fails 3 times in a session (on Codex, which sends no exit code: returns the same output 3 times), the assistant is told to stop retrying, form one hypothesis and save the dead end with `--note "Do not redo=…"`. `ws pack add discipline`, then `ws start` again in your repo.
- Starter packs for common repo types: `web`, `library` and `ml` (alongside `ios`) add a few rules each, such as using the repo's own scripts, keeping a public API stable, or never committing datasets. The first `ws start` suggests the one that fits the repo; nothing is added unless you run `ws pack add`.
- Claude Code plugin (preview): `/plugin marketplace add Alenroyfeild/ai-dev-workspace`, then `/plugin install ai-dev-workspace@ai-dev-workspace`. It brings the session-start brief, capture, the MCP tools and the handoff/pickup/lesson skills, and stays inactive outside repos where `ws start` has run.

### Improved
- Clearer messages: a mistyped command suggests close matches instead of listing every command; `ws doctor --text` drops empty parentheses, says "Last capture: not run yet" and labels connections "Workspace-level connections"; `ws digest <directory>` and `ws team init`/`link` without a remote say what to pass.
- `ws start` asks "Apply this setup?" and mentions private memory imports only when it previewed some, and its preview notes existing untracked files (such as your own `.mcp.json`) that stay hidden from `git status` until `ws start --undo`. The tutorial and setup guide now match real output and point newcomers to `ws start` first.
- A confirmation prompt with no input (for example when an assistant runs `ws sync` or `ws know add --team` without `--yes`) now stops with "No confirmation; use --yes or --dry-run." instead of a Python traceback, and repeating `ws know add`, `ws remember` or `ws lesson add` with `--team` after declining reuses the saved record instead of creating a duplicate.
- The brief now carries dead ends: approaches saved as "Do not redo" or "Failures" in the task appear on one line, so the next session in any assistant skips them. `/handoff` asks for them.
- Each session starts lighter: the MCP server lists 7 core memory tools by default instead of 28, about 1,360 fewer tokens of tool descriptions per session. Set `"mcp_tools": "all"` in workspace.json to list everything; other tools still work when called by name.
- Decisions you state in chat (not only corrections) are now saved by the assistant with `remember`, so they reach the next session as saved decisions rather than unverified captures. In a repo set up earlier, run `ws start` again to pick up the new instruction; saved memory is kept.
- After an upgrade, run `ws start` again in your repo: it refreshes the setup files it wrote (instructions, hooks, MCP config) for the new version, after showing them and asking. Files you edited are left alone and reported; saved memory is kept.
- The first-run preview is shorter: it lists the files to be created and asks once before setup.
- The session brief now says when a file named in the saved next action or decisions was deleted or renamed since the checkpoint (`gone since: export.py (now publish.py)`), including deletions not yet committed, so the next session does not chase a file that is no longer there.
- The brief also warns when uncommitted edits that existed at the last checkpoint are gone (`uncommitted edits gone: export.py (stashed or reset?)`), so a session does not build on work that was stashed or reset away.
- `ws doctor` reports repo hooks that point to a missing kit, Python or workspace (after a pipx reinstall, deleted checkout or Python upgrade), so a silently memory-less session is caught; running `ws start` again in that repo refreshes them.

### Fixed
- Source builds and installed CLI/MCP entry points work from the packaged kit, including builds through pip.
- `ws doctor` reports your saved automatic team-pull consent instead of saying pulls are not active yet. [Team setup](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/docs/TEAM-WORKSPACE.md).
- Assistant hooks (`ws brief`, `ws nudge`, `ws paste`, and the opt-in guard and discipline hooks) no longer exit 2, print a traceback or block a prompt or session end when their input is malformed, the workspace is missing or corrupt, or a transcript is unreadable; they allow the action and print `{}`. A bad `cwd` no longer hides the session brief. A large prompt is still saved and blocked.
- Redaction (used for team sharing, captures and PR notes) now also hides bare provider tokens recognisable by prefix: GitHub (`ghp_`, `github_pat_`), OpenAI-style `sk-`, Slack `xox*-` (all prefixes, including `xoxc-` and `xoxd-`), AWS `AKIA` key IDs, GitLab `glpat-`, Google API keys `AIza`, npm `npm_`, Hugging Face `hf_` and Stripe `sk_`/`rk_` `live_`/`test_` keys (Anthropic `sk-ant-` is covered by `sk-`).
- `ws validate` and `ws doctor` no longer call a fresh `ws start` setup invalid: a task that has never been checkpointed may have no next action yet.
- Repo-local `workspace.json` cannot override an existing memory link; invalid links stop with a repair hint. [Commands](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/docs/COMMANDS.md#set-up).
- Two memory updates at the same moment (for example a Stop hook capturing while the assistant saves a decision) no longer reject one of them: a save now waits up to 4 seconds for the other to finish instead of failing at once, so the hook is not reported as an error and the capture is not skipped.
- A later `Do not redo` or `Failures` note no longer erases the dead ends saved earlier; new ones are added and repeats are not duplicated. Edit the task file to drop one.
- `ws pack add <name>` now takes the workspace lock and writes `workspace.json` atomically, so an interrupted add cannot leave it truncated.
- `ws pack add --from` and `ws pack remove` no longer garble non-ASCII text in your `AGENTS.md` on systems whose default text encoding is not UTF-8 (for example Windows).
- On Windows, non-ASCII text (accented names in paths, notes, `AGENTS.md`, git output) is read and written as UTF-8, the pip/pipx `ws` command prints it correctly, Codeburn runs when installed as a `.cmd` shim, `ws upgrade` recognises its own quoted hooks, and the guards pack blocks a home-folder delete written with `/` or different capitalisation.
- MCP tools now reject odd or hostile arguments with a clear error instead of crashing the server or corrupting the task record: deeply nested or non-UTF-8 requests, huge numbers, text over 100,000 characters, unknown task IDs, and text that tried to start a new section, add task metadata, forge `ws` markers or carry `<private>` spans. `search_sessions` also hides `<private>` text and `#private` messages.
- An unclosed `<private>` marker now hides the rest of the text everywhere (capture, `ws remember`, export, session search), not only in saved notes.
- A team folder file that is not valid UTF-8 now stops `ws team link --folder` and `ws sync --pull-only` with a message naming the file instead of a Python traceback; the local mirror is left unchanged. A new branch's first brief now shows team onboarding like any fresh task, and with more than 100 team entries it shows the newest product, domain and repo notes without a false "unreadable entries" warning.

### Known limits
- The `uncommitted edits gone` warning covers tracked files only: a new untracked file deleted after the checkpoint, or a file edited again with different uncommitted changes, is not reported.
- The Claude Code plugin (preview) and the repo connection from `ws start` both add hooks; use one of them per repo, or each session gets two briefs.
- Folder snapshots are read-only and do not provide realtime sync or protection from concurrent external edits.
- Automatic team pulls require a Git remote and consent; only macOS gets the built-in daily scheduler.

## 0.1.0-beta.4 (2026-10-15)

Start memory from inside your own repo with one command, keep a decision with `ws remember`, and see at session start what was remembered. A private team workspace arrives as a preview.

### Highlight: your team's knowledge in every session (preview)
Share a fact once and every teammate's assistant starts with it. Your notes stay private until you approve a preview; teammates see shared notes in their brief, labelled as team context, after their own decisions.

```bash
ws team init <private-repo>
ws know add "Payments API rejects floats; send integer cents" --category domain --team
ws sync
# a teammate: ws team link <private-repo>, then their next brief shows it
```
Product, feature, domain and repo knowledge, plus runbooks from finished tasks. [Team quick start](https://github.com/Alenroyfeild/ai-dev-workspace/blob/v0.1.0-beta.4/docs/TEAM-WORKSPACE.md#quick-start).

### New
- Link a personal workspace to a private team workspace. New notes stay private; preview what will be shared, then choose what to share or remove. `ws sync` shows incoming changes and publishes only the copies you approved.
- Add categorized team knowledge, generated index cards, and turn a finished task into a shareable runbook. [Team workspace guide](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/docs/TEAM-WORKSPACE.md).
- Team knowledge in your brief: relevant shared cards appear after your own decisions and next action, labelled untrusted with author and date. A shared note that largely repeats one of your private decisions is left out, so your decision wins. Search lists your own results first.
- Optional team status: `ws team status "Checking receipts" --author sam --publish-status` previews a short "working on" line (alias, task title, date) before saving it. Off by default; teammates see it marked as last reported, not live.
- Install and start without `pipx`: the quick start includes a virtual-environment path.

### Improved
- `ws remember "use Postgres, not SQLite"` saves one decision in your current task, and the next session's brief shows it ahead of automatically captured notes. Assistants can save one too through the new MCP `remember` tool, so a decision you state in chat holds in later sessions.
- At session start, Claude Code and Codex now show you one line such as `Remembered: 3 decisions · next: write the migration`, so you can see the saved memory was loaded. With nothing saved, it tells you how to save something.
- Team sync checks the exact approved text before publishing; on Windows it preserves CRLF line endings. It never pushes unrelated local commits.

### Fixed
- `ws start` gives new tasks readable branch IDs and leaves Next action unsaved until you supply it. Existing tasks and decisions are preserved. [Repo setup](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/docs/REPO-START.md).
- Codex session-start memory survives a missing transcript and read-only usage metadata. Plain brief and MCP memory reads need no write access. [Setup and hook trust](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/docs/SETUP.md).
- `ws connect claude` and `ws connect codex` no longer add skills to your global `~/.claude` or `~/.agents` folders without asking. Project skills work as before; add `--skills` to link the extra ones globally. Skills you already linked are left alone.
- `ws doctor` and `ws update --check` never reported new versions, because GitHub hides beta releases from its "latest release" lookup. They now see beta releases and show the release summary.

### Measured
- Release check on macOS at the release candidate, in a throwaway home and sample repo: `ws start`, `ws remember`, a checkpoint, then a new real session in Claude Code and in Codex CLI 0.155.1. Both answered the remembered decision and next action from startup memory; `ws start --undo` left `git status` empty.
- CI passes on macOS, Linux and Windows at the release candidate; the release dry run passed in normal, offline and shallow-clone modes.

### Known limits
- Team workspace is a preview: sharing and sync are tested with local bare repositories only. Automatic and scheduled pulls are not in this release.
- Corrections spoken only in chat are not reliably saved yet. Use `ws remember` to keep a decision; see the beta.3 measured result for the current correction-capture limits.

## 0.1.0-beta.3 (2026-10-12)

Your saved decisions now survive long handoffs, the MCP server works with clients on the newest protocol, and Google ADK and LangGraph agents can share the same task memory.

### Improved
- Session-start hooks create local tasks for new git branches and switch the brief with the branch. Existing decisions and claims are preserved; `capture:false` disables automatic task creation. [Branch memory](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/README.md#what-you-get).
- Start inside your code repo with `ws start`: preview local files, confirm once, connect detected assistants and claim a task for the branch. Existing files are preserved; running it again only shows status. [Quick start](https://github.com/Alenroyfeild/ai-dev-workspace/blob/dev/README.md#quick-start-2-minutes).
- **Decisions come first in the session brief.** A long checkpoint (blockers plus a handoff) used to push saved decisions past the 200-word limit, so the next session never saw them. Each section now has its own budget, decisions and corrections are kept first, and the brief points to the task file when it has to cut.
- **Works with new and old MCP clients.** Clients on the 2026-07-28 MCP spec (no handshake, version on every request) connect directly; clients on 2025-11-25 and 2025-06-18 work as before. Tested with the official Python MCP SDK in both modes.
- **Google ADK and LangGraph recipes.** Opt-in examples connect agents to your workspace over MCP with only four tools exposed (find task, brief, checkpoint, add lesson). A decision saved by one framework was picked up by a fresh agent in the other, both ways. See [docs/examples/frameworks](https://github.com/Alenroyfeild/ai-dev-workspace/blob/v0.1.0-beta.3/docs/examples/frameworks/README.md).
- **Safer setup.** `ws setup` shows which assistants and project connections it will change before it changes them, and tells you what to do if a step fails.
- **Team work.** Shared workspaces show the tasks and claims for your current branch and flag task files that conflict.
- **Clearer health check.** `ws doctor --mcp` checks every configured client; `ws doctor` separates "configured" from "last proven working".

### Fixed
- Task files edited on Windows keep their line endings.
- Team claims and conflicts stay readable when several people share a workspace.
- Command examples in the README, TEAM and SETUP guides now match the real commands and are tested on every change.

### Measured
- Handing decisions from Claude Code to Codex: 5/5 with the workspace, 0/5 without (unchanged from beta.2).
- Hard rollout test, where the user corrects the assistant mid-task: workspace 2/5, a plain Markdown notes file 5/5, nothing 0/5. Corrections said only in chat are not yet captured into the task, so the brief cannot carry them. This is the main fix planned for beta.4. Details: [bench/README.md](https://github.com/Alenroyfeild/ai-dev-workspace/blob/v0.1.0-beta.3/bench/README.md).

### Known limits
- The new MCP protocol was tested with the Python SDK, not yet with a live assistant.
- The ADK and LangGraph recipes were tested with stub models, not hosted ones.

## 0.1.0-beta.2 (2026-10-09)

### Proven
- Decisions given in Claude Code were followed by Codex in 5/5 runs with the workspace and 0/5 without (benchmark `--resume-provider`); Claude Code to Claude Code also 5/5 vs 0/5. See docs/MEASUREMENTS.md.

### New
- Stale-memory check: the brief warns when files named in the next action changed since the checkpoint, or when the code was rolled back past it; lessons whose files are gone are marked.
- `ws next`, `ws task depend` and `ws task import` (Spec Kit `tasks.md`, Task Master `tasks.json`).
- Copilot and Cursor get the current task in their own instruction files.
- `ws import native` reads Claude, Codex and Gemini built-in memories into a task (read-only, preview first); `ws status` shows Codex goal status.
- Privacy: `<private>` text and `#private` messages are never captured, home paths become `~`, more secrets are redacted, and `"capture": false` turns capture off.
- `ws paste` and `ws digest --focus` keep big logs out of the conversation.
- A session that changed files without updating its task is asked once to checkpoint.
- Plain, readable output in a terminal (JSON when piped or with `WS_JSON=1`).

### Fixed
- The session-start brief now keeps every numbered decision (a regression that hid them from non-Claude clients).
- First-run: `ws init` no longer prints a Codex config block to everyone; new workspaces are not offered selftest or install suggestions.

## 0.1.0-beta.1

This beta gives you a small, local workspace for carrying task context between coding sessions.

### What you can do

- Keep tasks, claims, checkpoints, lessons and session notes in plain files. Claude Code and Codex can load workspace rules, skills and MCP tools.
- Capture decisions from supported session transcripts; every capture is unverified and can be reviewed in the task record.
- Map a code checkout and search its map, notes and local session history. `ws map` can link an existing Graphify report; it never runs Graphify.
- Route work with `ws route` and run a bounded, read-only explorer with `ws delegate`. Run `ws delegate --selftest --provider codex` to check the current sandbox before using it.
- Browse the toolbox, see estimated tool load with `ws tools --cost`, and review `ws assist` suggestions before applying them. Upgrade existing workspaces with `ws upgrade`; user content is preserved and conflicts are staged as `.ws-new`.
- Use MCP prompts in clients without native skills, keep private packs locally, or delegate a read-only review of a diff. Security checks protect workspace paths and client configuration.
- Search Cursor and Gemini CLI session history, run the `bench/` continuity benchmark, and use grouped help or `--text` output in scripts. Cursor and Gemini session search are fixture-tested; client sessions remain untested live.
- Install the CLI with `pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace`.

In a measured test where Claude captured decisions automatically, the next session met all six hidden checks in 5/5 runs, versus 0/5 without the workspace. See [the method and limitations](docs/MEASUREMENTS.md).

### Client support

| Client | Status |
|---|---|
| Claude Code | Proven: rules, MCP tools, hooks, skills and automatic capture. |
| Codex | Proven: rules, MCP tools, hooks, skills and automatic capture. |
| Cursor | Rules, MCP tools, hooks and capture set up by `ws connect cursor`; untested live. |
| GitHub Copilot in VS Code | Rules and MCP tools set up by `ws connect vscode`; untested live. |
| Gemini CLI | Rules, MCP tools, hooks and capture set up by `ws connect gemini`; untested live. |

### Known limits

- Windows is supported; see [Windows notes](docs/WINDOWS.md).
- Captures are unverified and need review.
- Cursor, Copilot and Gemini CLI connections are documented but have not been tested in live client sessions.
