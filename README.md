# AI Dev Workspace  ·  beta

**Your AI assistant picks up where it left off: tasks, decisions and lessons in Markdown you own.**

AI coding assistants can lose task context between sessions. AI Dev Workspace stores task notes as Markdown in a folder you own and exposes them through a CLI, MCP server and client integrations. What each assistant can read or capture depends on the support table below.

macOS, Linux and Windows. Requires Python 3.9+ and git. No workspace account or telemetry; your assistant still sends prompts and context to its chosen provider.
On Windows, run `python bin/ws <command>` from the kit checkout; see [Windows notes](docs/WINDOWS.md).

**Measured:** when product decisions were given in one session, a fresh session finished the task following all of them in 5 of 5 runs with the workspace and 0 of 5 without it, for about $0.06 more per session. **Across assistants:** with decisions given in Claude Code and the task finished in Codex, 5 of 5 runs followed every decision with the workspace and 0 of 5 without it. Method and caveats: [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

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

This example is a Claude Code run. Codex is also proven; other clients provide the capabilities shown in the support table below.

## Quick start

```bash
pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace     # 1. install
ws init ~/work/myapp-ws --repo ~/code/myapp                            # 2. create a workspace
cd ~/work/myapp-ws && ws connect claude                                # 3. connect your assistant
ws task new APP-123 "Fix login crash" && ws claim APP-123              # 4. start a task
```

Run `ws brief` to see APP-123; until you checkpoint it, the next action is honestly reported as not saved.

Open the workspace folder in Claude Code (add your code folder as a working directory) and work as usual. End a session with `/handoff`; start the next one with anything, or `/pickup`. In Codex use `$handoff` and `$pickup` (proven in fresh `codex exec` sessions).

No pipx? `git clone https://github.com/Alenroyfeild/ai-dev-workspace ~/ai-dev-workspace` and put `~/ai-dev-workspace/bin` on your PATH. Connect Codex, Cursor, Copilot or Gemini CLI with `ws connect codex|cursor|vscode|gemini`. Full guide: [docs/SETUP.md](docs/SETUP.md).

## What you get

- **Task memory that writes itself.** One record per ticket: objective, evidence, blockers and next step. Claude and Codex hooks capture bounded, unverified decisions into Handoff. Cursor/Gemini hooks are wired and fixture-tested, but their clients remain untested. Other MCP clients use rules plus MCP only. Skills: `/handoff`, `/pickup`, `/lesson`.
- **Lessons.** "What happened → rule", matched to the task and surfaced in its brief to help avoid a repeated mistake.
- **An instant codebase map.** `ws map` writes languages and commands, links an existing Graphify report, and indexes it for `ws search`; it never runs Graphify.
- **Toolbox and assist.** `ws tools` lists optional tools. `ws assist` offers local workspace suggestions and asks before applying. Advanced profiles and cost details: [docs/ADVANCED.md](docs/ADVANCED.md).
- **Search and cost records.** Search vault notes, lessons and past chats; import Codeburn usage with `ws run import codeburn` and inspect it with `ws run report`.
- **Safe by default.** Existing user content is preserved; ambiguous files are staged beside the original as `.ws-new`. Recognized managed sections can change during upgrades.
- **Measured, not assumed.** `ws run log` / `ws run report` record which assistant did what, with tokens and time.

All commands: [docs/COMMANDS.md](docs/COMMANDS.md). See [Workspace concepts](docs/CONCEPTS.md) for a plain-language guide to tasks, memory and delegation.

## Client compatibility

| Capability | Claude Code | Codex | Cursor | Copilot | Gemini CLI |
|---|---|---|---|---|---|
| Rules | proven | proven | documented, untested | documented, untested | documented, untested |
| MCP tools | proven | proven | documented, untested | documented, untested | documented, untested |
| Hooks | proven | proven | documented, untested | fixture-tested, Local only | documented, untested |
| Skills | proven | proven | not wired yet (client supports skills) | not wired yet (client supports skills) | not wired yet (client supports skills) |
| Automatic capture | proven | proven | documented, untested | fixture-tested, v1 transcript only | documented, untested |

Copilot hooks here target the VS Code **Local** harness: `ws connect vscode` writes managed `.github/hooks/ai-dev-workspace.json`. Live editor execution is unverified. [Local hook inputs](https://code.visualstudio.com/docs/agents/reference/hooks-reference) provide an optional transcript path but warn that its format is unstable; unknown formats leave memory untouched. Agent Host Copilot uses a different SDK hook protocol and remains **rules plus MCP only** in this kit. [Choose the hook harness](https://code.visualstudio.com/docs/agent-customization/hooks).

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

Task notes stay in your workspace. Assistant prompts and context go to the provider you use. The kit checks for updates once a day unless `WS_OFFLINE=1`; hooks can save bounded, unverified captures. Delegation and feedback send data only when you explicitly run those commands; feedback is redacted and previewed first.

## Status

Beta (0.1.0-beta.1): tested (`python3 -m unittest discover -s tests`), and changing. When something gets in your way, your assistant offers to note it as feedback; that is how this improves. Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). How it fits together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Contributing and packs: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. The `codex-worker` pack downloads and patches `@agentclientprotocol/codex-acp` (Apache-2.0) on your machine; nothing of it is redistributed here.

Measured continuity: Codex met conversation-only decisions in **3/3 workspace completions versus 0/3 baseline** (n=3, 2026-10-07 UTC); both arms passed visible tests. Workspace runs took longer, so this is a quality result, not a savings claim. Reproduce it with [bench/](bench/README.md); see [measurements and limits](docs/MEASUREMENTS.md).
