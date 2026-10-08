# AI Dev Workspace  ·  beta

**Your AI picks up exactly where it left off, in any assistant, and stops repeating the same mistakes.**

AI coding assistants forget everything between sessions. Every new chat re-reads the same files, re-discovers the same rules and repeats the same mistakes, and you pay for it in tokens and time. AI Dev Workspace gives Claude Code, Codex, Cursor and any MCP client one shared memory: plain Markdown files in a folder you own, a small CLI and an MCP server.

macOS and Linux only; Windows not supported yet (file locking uses fcntl). Requires Python 3.9+ and git. No API keys, account or telemetry.

**Measured:** when product decisions were given in one session, a fresh session finished the task following all of them in 5 of 5 runs with the workspace and 0 of 5 without it, for about $0.06 more per session. Method and caveats: [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

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

**Measured:** when product decisions were given in one session, a fresh session finished the task following all of them in 5 of 5 runs with the workspace and 0 of 5 without it, for about $0.06 more per session. Method and caveats: [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

## Quick start

```bash
pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace     # 1. install
ws init ~/work/myapp-ws --repo ~/code/myapp                            # 2. create a workspace
cd ~/work/myapp-ws && ws connect claude                                # 3. connect your assistant
ws task new APP-123 "Fix login crash" && ws claim APP-123              # 4. start a task
```

Open the workspace folder in Claude Code (add your code folder as a working directory) and work as usual. End a session with `/handoff`; start the next one with anything, or `/pickup`. In Codex the same skills are `$handoff` and `$pickup` (proven in fresh `codex exec` sessions).

No pipx? `git clone https://github.com/Alenroyfeild/ai-dev-workspace ~/ai-dev-workspace` and put `~/ai-dev-workspace/bin` on your PATH. Connect Codex, Cursor, Copilot or Gemini CLI with `ws connect codex|cursor|vscode|gemini`. Full guide: [docs/SETUP.md](docs/SETUP.md).

## What you get

- **Task memory that writes itself.** One record per ticket: objective, evidence, blockers and next step. Claude and Codex hooks capture bounded, unverified decisions into Handoff. Cursor/Gemini hooks are wired and fixture-tested, but their clients remain untested. Other MCP clients use rules plus MCP only. Skills: `/handoff`, `/pickup`, `/lesson`.
- **Lessons.** "What happened → rule", matched to the task and shown before the assistant starts, so a mistake made once is not made again.
- **An instant codebase map.** `ws map` writes languages and commands, links an existing Graphify report, and indexes it for `ws search`; it never runs Graphify.
- **Toolbox and assist.** `ws tools` lists recommended everyday tools, optional extras and caution tools that change routing/config. `ws assist` asks before applying; `ws tools --cost` measures schemas and skill/plugin size. Workspace profiles are `lean`, `standard` and `full`, with per-tool `on`, `off` or `ask` overrides.
- **Search and cost records.** Search vault notes, lessons and past chats; import Codeburn usage with `ws run import codeburn` and inspect it with `ws run report`.
- **Safe by default.** Your existing files are never overwritten; conflicts are written beside them as `.ws-new`. One claim per task, with stale-write protection.
- **Measured, not assumed.** `ws run log` / `ws run report` record which assistant did what, with tokens and time.

All commands: [docs/COMMANDS.md](docs/COMMANDS.md). See [Workspace concepts](docs/CONCEPTS.md) for a plain-language guide to tasks, memory and delegation.

## Client compatibility

| Capability | Claude Code | Codex | Cursor | Copilot | Gemini CLI |
|---|---|---|---|---|---|
| Rules | proven | proven | documented, untested | documented, untested | documented, untested |
| MCP tools | proven | proven | documented, untested | documented, untested | documented, untested |
| Hooks | proven | proven | documented, untested | not wired yet (client supports hooks) | documented, untested |
| Skills | proven | proven | not wired yet (client supports skills) | not wired yet (client supports skills) | not wired yet (client supports skills) |
| Automatic capture | proven | proven | documented, untested | not available | documented, untested |

## Optional packs

| Pack | Adds | Needs |
|---|---|---|
| `obsidian` | Open the memory as a linked, searchable Obsidian vault | [Obsidian](https://obsidian.md) |
| `local-llm` | Free on-device log triage | [Ollama](https://ollama.com) and a small model |
| `codex-worker` | Legacy ACP read-only worker; retained for existing users | Node, `acpx`, a Codex sign-in |
| `ios` | iOS build triage, Simulator debugging, App Store review runbooks | Xcode |

`ws pack add <name>`. Your own domain (Android, web, backend) is a folder with a `pack.json`: [docs/PACKS.md](docs/PACKS.md).

`ws delegate` is the supported read-only worker path. Run `ws delegate --selftest --provider codex` in your workspace to check the sandbox with a positive read control and hostile writes in throwaway directories; `ws doctor` shows the latest provider result. Codex passed these probes on macOS on 2026-10-07; rerun after changing the CLI or sandbox.

## Privacy

Everything stays in your folder. The only network call is a once-a-day check for a new release (`export WS_OFFLINE=1` turns it off). Nothing is updated, recorded or sent without your yes; feedback you choose to share is redacted and previewed first.

## Status

Beta (0.1.0-beta.1): tested (`python3 -m unittest discover -s tests`), and changing. When something gets in your way, your assistant offers to note it as feedback; that is how this improves. Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). How it fits together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Contributing and packs: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. The `codex-worker` pack downloads and patches `@agentclientprotocol/codex-acp` (Apache-2.0) on your machine; nothing of it is redistributed here.

Measured continuity: Codex met conversation-only decisions in **3/3 workspace completions versus 0/3 baseline** (n=3, 2026-10-07 UTC); both arms passed visible tests. Workspace runs took longer, so this is a quality result, not a savings claim. Reproduce it with [bench/](bench/README.md); see [measurements and limits](docs/MEASUREMENTS.md).
