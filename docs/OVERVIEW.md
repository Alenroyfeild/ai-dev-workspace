# Extended overview

[Back to the concise README](../README.md).

[![Tests](https://github.com/Alenroyfeild/ai-dev-workspace/actions/workflows/test.yml/badge.svg)](https://github.com/Alenroyfeild/ai-dev-workspace/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Alenroyfeild/ai-dev-workspace?include_prereleases)](https://github.com/Alenroyfeild/ai-dev-workspace/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)

**Your AI assistant picks up where it left off: tasks, decisions and lessons in Markdown you own.**

One shared memory for **Claude Code, Codex, Cursor, GitHub Copilot and Gemini CLI**. Decide something with Claude today, finish it with Codex tomorrow, and the decision is still followed. Plain files in a folder you own, a small CLI (`ws`) and an MCP server. No account, no telemetry, nothing to install beyond Python 3.9+ and git.

## Measured, not claimed

Same task, same prompts, fresh sessions. Product decisions were given only in conversation in session 1; session 2 had to finish the task and follow them (six hidden checks). Reproduce with [`bench/`](../bench/README.md); method and limits in [docs/MEASUREMENTS.md](MEASUREMENTS.md).

| Session 1 → session 2 | Without workspace | With workspace |
|---|---|---|
| Claude Code → Claude Code | 0/5 | **5/5** |
| Claude Code → Codex (different assistant) | 0/5 | **5/5** |
| Codex → Codex | 0/3 | **3/3** |

Later Codex → Codex runs (n=5 each) were less favourable: the workspace passed 1/5 and 2/5, while a plain `HANDOFF.md` control passed 4/5 and 5/5. See [bench/README.md](../bench/README.md).

In the first golden run, when product decisions were given in one session, a fresh session followed all of them in 5 of 5 runs with the workspace and 0 of 5 without, for about $0.06 more per session. Small n and synthetic tasks: this shows decisions surviving across sessions and assistants, not general productivity.

## What it looks like

A real run on the released beta (Claude Code, synthetic app). Session 1, with no `/handoff`:

```text
you:     The app crashes on an empty email at login (APP-123). Product decided today:
         an empty email must return 'missing_email', and signup must not change.
         Find the root cause, but don't edit yet. I have to leave.
```

Next day, a brand-new session:

```text
you:     hi
claude:  Picking up task APP-123 (fix login crash). Next action from the saved record:
         in app/auth.py's login(), catch the ValueError from normalize(email) and return
         {'ok': False, 'error': 'missing_email'}, without touching app/email.py or
         app/signup.py. Want me to go ahead and implement that fix now?
```

The decision was captured from the conversation and the session-start brief brought it back.

## Quick start (2 minutes)

```bash
pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace
cd ~/code/myapp && ws start
```

`ws start` creates local memory in this repository, connects detected assistants and claims a task named for your git branch. It previews project files before one confirmation; user files are preserved and conflicts are reported. Repeating it shows status. Use `--dry-run` for preview only or `--yes` for automation. Open this code repo in your assistant and trust project hooks/MCP when asked. Memory is saved by hooks and checkpoints; `/handoff` and `/pickup` (Codex: `$handoff`, `$pickup`) are there when you want to be explicit. No pipx? Clone the repo and put its `bin/` on your PATH. Windows: `python bin/ws <command>`, see [Windows notes](WINDOWS.md). For a separate workspace, use `ws init`; full guide: [SETUP.md](SETUP.md).

Hands-on walkthrough with a throwaway repo: [TUTORIAL.md](TUTORIAL.md).

## What you get

**Memory that follows the work**
- One Markdown record per task: objective, evidence, blockers, next action, handoff. Hooks for Claude, Codex, Cursor, Gemini CLI and VS Code Copilot capture conversation decisions automatically (see Client compatibility for what is proven); a short brief (under 200 words) is injected at every session start.
- **Stale-memory check**: the brief warns when files named in the next action changed since it was written, or when the code was rolled back past the checkpoint. It also names files deleted or renamed since the checkpoint and uncommitted edits that were reset away.
- **Dead ends**: tried-and-failed approaches from the task's Do not redo and Failures sections appear in the brief as `Do not redo:`, so a new session does not retry them.
- **Lessons** ("what happened → rule"), ranked by the files you are changing, so a mistake made once is not repeated.
- Search vault notes, lessons and past Claude, Codex, Cursor and Gemini sessions (`ws sessions search`).

**Works with your assistant's own features**
- Copilot and Cursor get the current task in their own instruction files (`.github/copilot-instructions.md`, a Cursor rule), so decisions reach them even without hooks.
- `ws import native` brings existing Claude, Codex and Gemini built-in memories into the task (read-only, preview first); `ws status` shows Codex goal status beside your task.
- Route roles to the models you prefer (`routing.json`), delegate read-only work to a second assistant (`ws delegate`), and see what your tools cost in context (`ws tools --cost`).

**Task flow**
- Claims so two sessions do not edit the same task; a session that changed files without updating its task is asked once to checkpoint.
- `ws next` shows work that is not blocked; `ws task depend` and `ws task import` (Spec Kit `tasks.md`, Task Master `tasks.json`).
- `ws pr-notes` prints a task's decisions, reasons, tried-and-rejected approaches and checks as a PR description; `ws recap` lists the week's tasks and decisions.

**Try and check**
- `ws demo` saves a sample decision in a disposable workspace and reads it back in a fresh process, offline, without starting an assistant.
- `ws audit` scores a repo's AI setup (instructions and their size, broken file references, memory, hooks, MCP server count, stale tasks) and lists up to 3 fixes. Read-only and offline.

**Trust**
- Plain files you can read, diff, commit and share. Existing files are never overwritten; proposals go beside them as `.ws-new`.
- Captures are redacted (keys, tokens, credential URLs), home paths become `~`, `<private>` text is never stored, and `"capture": false` turns capture off.
- A confirmation prompt with no input (an assistant running `ws sync` without `--yes`) stops with a message instead of a traceback.
- Big pastes go to a local inbox instead of your context (`ws paste`, `ws digest --focus`).

All commands: [docs/COMMANDS.md](COMMANDS.md). Plain-language guide: [docs/CONCEPTS.md](CONCEPTS.md).

## How it compares

| | AI Dev Workspace | Manual HANDOFF.md | Built-in assistant memory | claude-mem | Beads |
|---|---|---|---|---|---|
| Works across different assistants | yes, measured Claude → Codex | yes, if each is told to read it | one assistant | Claude Code | yes, through its CLI/MCP |
| Plain files you can commit and share | yes, Markdown | yes, one file | per-machine local store | local store | yes, git-backed |
| Captures conversation decisions automatically | yes (Claude, Codex hooks) | no, written by hand at the end | when the model chooses to | yes | no, the agent files issues |
| Task status, claims and dependencies | yes | yes, edited by hand | per tool (Claude Tasks, Codex goals) | no | yes |
| Warns when memory may be stale | yes | no, relies on dates | not documented | not documented | not applicable |
| Published, reproducible benchmark | yes, [bench/](../bench/README.md) | no | no | no | no |

Use it with them, not instead: `ws import native` reads built-in memories, `ws task import` reads Spec Kit and Task Master output, and it runs alongside skill packs in the same session.

Already writing a HANDOFF.md by hand? `ws checkpoint` saves the same state and next step per task, and the brief hands them to whichever assistant opens the repo next. Handoff patterns compared in [codex-claude-code-config](https://github.com/AnastasiyaW/codex-claude-code-config/blob/main/alternatives/session-handoff.md).

## Client compatibility

| Capability | Claude Code | Codex | Cursor | Copilot | Gemini CLI |
|---|---|---|---|---|---|
| Rules | proven | proven | fixture-tested | fixture-tested | fixture-tested |
| MCP tools | proven | proven | fixture-tested | fixture-tested | fixture-tested |
| Hooks | proven | proven | fixture-tested | fixture-tested, Local only | fixture-tested |
| Skills | proven | proven | not wired yet (client supports skills) | not wired yet (client supports skills) | not wired yet (client supports skills) |
| Automatic capture | proven | proven | fixture-tested | fixture-tested, v1 transcript only | fixture-tested |

"Proven" means exercised in real sessions of that client. "Fixture-tested" means automated tests check the generated config and hook input/output against saved fixtures and the client's docs; no live session was run. Copilot hooks target the VS Code Local harness ([details](SETUP.md)).

## FAQ

**Claude Code and Codex already have memory. Why this?** Built-in memory belongs to one assistant on one machine, and the model decides what to keep. This keeps task state and decisions in files every assistant reads at session start, and it is measured: decisions given in Claude were followed by Codex in 5 of 5 runs.

**Is it another CLAUDE.md?** No. Rules files say how to work; this records what is happening: the current task, its next action, decisions, blockers and lessons, updated as you work and kept short.

**Does it send my code anywhere?** No. Everything is local files. Your assistant still sends prompts to its own provider; the kit only checks GitHub for a new release once a day (`WS_OFFLINE=1` turns that off).

**Does it cost tokens?** The brief is under 200 words. In the benchmark a completion session cost about $0.05 to $0.06 more with the workspace ($0.047 and $0.058 in the two Claude runs in [MEASUREMENTS.md](MEASUREMENTS.md)); the gain is correctness across sessions, not lower spend.

**Can a team share it?** The workspace is plain files: commit it to a private repo. Claims show who is working on which task. A team can also link a synced folder and read its shared notes, read-only (`ws team link /path/to/shared-folder --folder --attest-private`). See [docs/TEAM.md](TEAM.md).

## Optional packs

| Pack | Adds | Needs |
|---|---|---|
| `obsidian` | Open the memory as a linked Obsidian vault | [Obsidian](https://obsidian.md) |
| `local-llm` | Free on-device log triage | [Ollama](https://ollama.com) and a small model |
| `ios` | iOS build triage, Simulator debugging, App Store review runbooks | Xcode |
| `guards` | Claude Code and Codex hooks (Windows PowerShell too) that deny `rm -rf` / `Remove-Item -Recurse -Force` on home or root, `git reset --hard`, force push, `git clean -f`, secrets in commands or files, and newly skipped tests. Run `ws start` again in each repo after adding or removing it; `WS_GUARDS=off` turns it off for one session. A safety net for honest mistakes, not a security boundary | nothing |
| `discipline` | Advisory only: after the same shell command fails 3 times in a session, Claude Code and Codex are told to stop retrying, form one hypothesis and save the dead end. Never blocks; stores a hash of the command, not the text | nothing |
| `web`, `library`, `ml` | A few starter rules for that kind of repo (under 70 words each); the first `ws start` suggests the one that fits | nothing |
| `codex-worker` | Legacy ACP read-only worker, kept for existing users | Node, `acpx`, a Codex sign-in |

`ws pack add <name>`. Your own domain is a folder with a `pack.json`: [docs/PACKS.md](PACKS.md).

## Privacy and status

Task notes stay in your workspace; delegation and feedback send data only when you run them, and feedback is previewed first. Beta: tested on macOS, Linux and Windows (`python3 -m unittest discover -s tests`) and released often; see [CHANGELOG.md](../CHANGELOG.md) and [docs/ROADMAP.md](ROADMAP.md). How we build it: [docs/PRINCIPLES.md](PRINCIPLES.md). Architecture: [docs/ARCHITECTURE.md](ARCHITECTURE.md). Contributing and packs: [CONTRIBUTING.md](../CONTRIBUTING.md).

## License

MIT. The `codex-worker` pack downloads and patches `@agentclientprotocol/codex-acp` (Apache-2.0) on your machine; nothing of it is redistributed here.
