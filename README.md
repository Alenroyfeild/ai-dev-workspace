# AI Dev Workspace  ·  beta

**Your AI picks up exactly where it left off, in any assistant, and stops repeating the same mistakes.**

AI coding assistants forget everything between sessions. Every new chat re-reads the same files, re-discovers the same rules and repeats the same mistakes, and you pay for it in tokens and time. AI Dev Workspace gives Claude Code, Codex, Cursor and any MCP client one shared memory: plain Markdown files in a folder you own, a small CLI and an MCP server.

No API keys, no server, no account, no telemetry. Python 3.9+ and git are all it needs.

## What it looks like

A real run, lightly trimmed (Claude Code, synthetic task). Session 1 ends with:

```text
you:     /handoff DEMO-1. Crash reproduced; cause is a force-unwrap of email in
         LoginValidator.swift:42. Next: add an empty-email guard and run LoginValidatorTests.
claude:  (saves the checkpoint with `ws`)
```

The next day, a brand-new session that remembers nothing:

```text
you:     hi
claude:  I've got a task waiting from your earlier session:
         DEMO-1: Fix login crash on empty email
         Next action: Add empty-email guard in LoginValidator.validate()
         (LoginValidator.swift:42) and run LoginValidatorTests
         Ready to pick up where you left off?
```

No pasting old chats, no "where were we". The same memory works from Codex or any MCP client.

## Quick start

```bash
pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace     # 1. install
ws init ~/work/myapp-ws --repo ~/code/myapp                            # 2. create a workspace
cd ~/work/myapp-ws && ws connect claude                                # 3. connect your assistant
ws task new APP-123 "Fix login crash" && ws claim APP-123              # 4. start a task
```

Open the workspace folder in Claude Code (add your code folder as a working directory) and work as usual. End a session with `/handoff`; start the next one with anything, or `/pickup`.

No pipx? `git clone https://github.com/Alenroyfeild/ai-dev-workspace ~/ai-dev-workspace` and put `~/ai-dev-workspace/bin` on your PATH. Codex and Cursor: `ws connect codex` / `ws connect cursor`. Full guide: [docs/SETUP.md](docs/SETUP.md).

## What you get

- **Task memory that writes itself.** One record per ticket: objective, evidence, blockers, the exact next step. A session-start hook feeds it to the assistant; a stop hook asks for a checkpoint when one is overdue. Skills: `/handoff`, `/pickup`, `/lesson`.
- **Lessons.** "What happened → rule", matched to the task and shown before the assistant starts, so a mistake made once is not made again.
- **An instant codebase map.** `ws init --repo` writes the languages, build and test commands, folders and most-changed files, with no model and no tokens spent.
- **Search instead of re-reading.** Vault notes, lessons, big logs (`ws digest`), and your past Claude and Codex conversations (`ws sessions search "why did we drop X"`).
- **Safe by default.** Your existing files are never overwritten; conflicts are written beside them as `.ws-new`. One claim per task, with stale-write protection.
- **Measured, not assumed.** `ws run log` / `ws run report` record which assistant did what, with tokens and time.

All commands: [docs/COMMANDS.md](docs/COMMANDS.md).

## Optional packs

| Pack | Adds | Needs |
|---|---|---|
| `obsidian` | Open the memory as a linked, searchable Obsidian vault | [Obsidian](https://obsidian.md) |
| `local-llm` | Free on-device log triage | [Ollama](https://ollama.com) and a small model |
| `codex-worker` | Codex as a **read-only** second AI, with a hostile self-test | Node, `acpx`, a Codex sign-in |
| `ios` | iOS build triage, Simulator debugging, App Store review runbooks | Xcode |

`ws pack add <name>`. Your own domain (Android, web, backend) is a folder with a `pack.json`: [docs/PACKS.md](docs/PACKS.md).

## Privacy

Everything stays in your folder. The only network call is a once-a-day check for a new release (`export WS_OFFLINE=1` turns it off). Nothing is updated, recorded or sent without your yes; feedback you choose to share is redacted and previewed first.

## Status

Beta (0.1.0-beta.1): tested (`python3 -m unittest discover -s tests`), and changing. When something gets in your way, your assistant offers to note it as feedback; that is how this improves. Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). How it fits together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Contributing and packs: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. The `codex-worker` pack downloads and patches `@agentclientprotocol/codex-acp` (Apache-2.0) on your machine; nothing of it is redistributed here.
