# AI Dev Workspace

Your assistant remembers work between sessions in Markdown you own. Shared, durable task memory for developers who switch between Claude Code, Codex, and other assistants.

[![PyPI version](https://img.shields.io/pypi/v/ai-dev-workspace)](https://pypi.org/project/ai-dev-workspace/) [![CI](https://github.com/Alenroyfeild/ai-dev-workspace/actions/workflows/test.yml/badge.svg)](https://github.com/Alenroyfeild/ai-dev-workspace/actions) [![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<!-- Demo GIF -->
![Switch from Claude Code to Codex: the saved decision follows the task (animation)](https://raw.githubusercontent.com/Alenroyfeild/ai-dev-workspace/main/docs/demo.gif)

## Quick start

Try offline before connecting a repo: `ws demo` · [5-minute tutorial](docs/TUTORIAL.md) · [Claude Code + Codex guide](docs/guides/share-memory-claude-code-codex.md) · [remove it](docs/TUTORIAL.md#remove-it)

```bash
pipx install ai-dev-workspace --pip-args='--pre'  # beta; omit --pip-args after a stable release
cd ~/code/myapp && ws start
```

No pipx? `brew install pipx`, or `python3 -m venv ~/.ws && ~/.ws/bin/pip install --pre ai-dev-workspace`; put its `bin` directory on `PATH` before `ws start`.

Prefer a Claude Code plugin? Preview. Not yet listed in Anthropic's official plugin directory; install from our GitHub marketplace:
```text
/plugin marketplace add Alenroyfeild/ai-dev-workspace
/plugin install ai-dev-workspace@ai-dev-workspace
```
Live-checked on beta.5 (2026-10-22). See the [plugin preview](docs/ADVANCED.md#claude-code-plugin-preview).

`ws start` previews every file and writes nothing until you confirm. Generated assistant hooks and configs stay local (`.git/info/exclude`), task memory lives outside the repo in `~/.ai-dev-workspace/<repo-name>`, and `ws start --undo` cleanly removes repo wiring.

<!-- videos:start -->
### Watch (videos for 0.1.0b6)

- [Watch the 2-minute explainer](https://youtu.be/sfcBNSELq-8)
- [Under the hood: real commands, real output](https://youtu.be/ZmwwgYzZUJY)
- Feature shorts: [Switch assistants](https://youtu.be/GAX8Jbl4KqY) · [Resume the next step](https://youtu.be/d4iicMtNq0o) · [Dead ends](https://youtu.be/Pf5JuXsKz98) · [Skills](https://youtu.be/NI69JfxGR_s) · [Team workspace (Preview)](https://youtu.be/-BlKcnaS6yM) · [Guards](https://youtu.be/_jmPEb2wSj4) · [Assistants](https://youtu.be/R6-hfqvz1YA) · [Install as a plugin (Preview)](https://youtu.be/BnbVLSl1vVs)
- Earlier editions: [0.1.0b5](https://youtu.be/w5EwQNO8Lz0)
<!-- videos:end -->

## Use cases

- **Switch Claude Code ↔ Codex mid-task:** Start in Claude Code, save a checkpoint, and continue in Codex with the exact same brief and task memory ([guide](docs/guides/share-memory-claude-code-codex.md)).
- **Resume tomorrow without re-explaining:** Inject active tasks, recent decisions, and blockers directly into context at session start ([tutorial](docs/TUTORIAL.md)).
- **Stop retrying failed approaches:** Dead ends appear under `Do not redo:` in every fresh session brief ([guide](docs/guides/stop-retrying-failed-approaches.md)).
- **Keep verified corrections:** Record decisions or constraints with `ws remember` so fresh sessions follow earlier rulings ([commands](docs/COMMANDS.md#save-a-correction)).
- **Block risky commands and leaks:** Opt-in `guards` pack denies dangerous shell operations and secrets in commands or written files ([packs](docs/PACKS.md)).
- **Share domain notes with a team (preview):** Share approved knowledge via private git repository with consent-based previews ([team](docs/TEAM-WORKSPACE.md)).

## Example

```text
Session 1 — You: “Empty email returns missing_email; leave signup unchanged.”
Assistant: “I’ll trace login and keep the decision with this task.”
You: “Save a checkpoint and stop here.”

Session 2 — You: “Continue the login fix.”
Assistant: “The saved note says return missing_email and leave signup unchanged.”
You: “Yes, continue.”
```

## Features

| Feature | Status | What it does | Docs link |
|---|---|---|---|
| Session brief | Stable | Injects bounded task memory, decisions, and blockers at session start | [Overview](docs/OVERVIEW.md) |
| Decisions & handoffs | Stable | Saves status, next action, and explicit rulings (`ws checkpoint`, `ws remember`) | [Commands](docs/COMMANDS.md) |
| Dead ends | Stable | Records failed approaches and displays them as `Do not redo:` | [Concepts](docs/CONCEPTS.md) |
| Lessons | Stable | Captures reusable cross-task takeaways and guidance (`ws lesson`) | [Commands](docs/COMMANDS.md) |
| MCP server | Stable | Exposes 7 core tools by default; others by name on request via stdio | [MCP](docs/MCP.md) |
| Guards pack | Stable | PreToolUse hook denies risky commands and secrets before execution | [Packs](docs/PACKS.md) |
| Discipline pack | Stable | Advisory nudge when the same command fails repeatedly in a session | [Packs](docs/PACKS.md) |
| `ws digest` | Stable | Compresses verbose terminal output into focused markdown notes | [Commands](docs/COMMANDS.md#search-and-lessons) |
| Native imports | Stable | Reads existing Claude and Codex memory files (`ws import native`) | [Commands](docs/COMMANDS.md#import-existing-memory) |
| `ws import claude-mem` | Preview | Fixture-tested SQLite copy import; newer upstream schemas may not import | [Advanced](docs/ADVANCED.md#import-a-claude-mem-copy) |
| `ws audit` | Stable | Read-only stack/wiring suggestions from bounded local manifests; no login or live-client proof | [Commands](docs/COMMANDS.md#daily-use) |
| `ws demo` | Stable | Creates an isolated sandbox repo to test commands safely | [Tutorial](docs/TUTORIAL.md) |
| Claude Code plugin | Preview | Hooks + MCP; needs CLI + `ws start`; not in Anthropic directory; Windows untested | [Advanced](docs/ADVANCED.md#claude-code-plugin-preview) |
| Codex plugin | Preview | Hooks need a trusted manual desktop install; no MCP; hooks not live-tested | [Advanced](docs/ADVANCED.md#codex-plugin-preview) |
| Cursor plugin | Preview | Fixture-tested only; not submitted; no verified install command | [Advanced](docs/ADVANCED.md#cursor-plugin-preview) |
| Worker fallback chain | Preview | Only declared providers and read-only roles run; timeout is a failed attempt | [Advanced](docs/ADVANCED.md#routing) |
| Gateway provider | Preview | Local fake-server tests only; sends a redacted brief to configured base_url, without tools | [Advanced](docs/ADVANCED.md#openai-compatible-gateway-preview) |
| Compact MCP recall | Stable | Bounded note cards and explicit untrusted detail; CLI snippets unchanged | [Advanced](docs/ADVANCED.md#compact-mcp-recall) |
| Lesson promotion | Stable | Repeated-note similarity suggests a draft; no automatic rule installation | [Advanced](docs/ADVANCED.md#draft-a-rule-from-repeated-lessons) |
| `digest_file` MCP tool | Preview | Opt-in size-only advice; scoped file summaries, no automatic compression | [Packs](docs/PACKS.md#optional-digest-advice) |
| Behavior pack | Stable | Opt-in engineering guidelines; advice, not enforcement or learned session patterns | [Packs](docs/PACKS.md#behavior-guidelines) |
| Skills packaging | Stable | Format checked; third-party installer not verified; CLI and setup still required | [Skills](docs/SKILLS.md) |
| Team sharing | Preview | Private git-backed knowledge repo with consent-based pulls and previews | [Team](docs/TEAM-WORKSPACE.md) |
| MCP Registry | Preview | Pre-configured `server.json` catalog entry for MCP client discovery | [MCP](docs/MCP.md) |

## How it works

```text
Claude Code / Codex / Cursor / Copilot / Gemini / Antigravity
        │ (session startup & capture hooks)
        ▼
~/.ai-dev-workspace/<repo-name>/           (private, outside repo)
  ├── workspace.json                       (settings, active task, packs)
  └── vault/
      ├── Tasks/<id>.md                    (status, next action, decisions, blockers)
      └── Learnings.md                     (reusable cross-task lessons & dead ends)
        ▲
        │ (MCP stdio connection: 7 core tools by default; others by name)
  Local Assistant (MCP client)
```

Memory storage makes no background model calls. `ws delegate --run` starts only declared assistant CLIs or sends a redacted brief to an explicitly configured gateway; output is unverified. Task memory is plain Markdown you own.

## Results

Measured in [`bench/README.md`](bench/README.md) across independent paired investigations (Codex `gpt-6-luna`, n=5 per cohort):

| Arm | Pass (October 11) | Pass (October 10) |
|---|---|---|
| Fresh baseline (no memory) | 0/5 | 0/5 |
| Workspace (automatic brief) | 2/5 | 1/5 |
| Plain Markdown handoff | 5/5 | 4/5 |

The latest controlled runs show the plain Markdown handoff beating the workspace (5/5 and 4/5 against 2/5 and 1/5), with the automatic-capture release gate still unmet. The win for the workspace is structure, cross-assistant handoff, and avoiding manual file management. Details and earlier runs: [bench/README.md](bench/README.md) and [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

## Compared with

- **Built-in memory files (CLAUDE.md, AGENTS.md):** Plain instructions per assistant; `ai-dev-workspace` adds cross-assistant handoffs, active task state, and `Do not redo:` constraints.
- **A plain HANDOFF.md:** Works well for manual notes (and beat automatic workspace capture in latest benchmark cohorts: 5/5 vs 2/5); `ai-dev-workspace` adds cross-assistant automation, structured brief injection, and staleness warnings.
- **claude-mem:** Captures tool use through hooks and compresses it with AI into SQLite + vector search ([upstream docs](https://github.com/thedotmack/claude-mem)), providing automatic memory capture without explicit commands; `ai-dev-workspace` keeps explicit Markdown you own, makes no background model calls for memory (explicit delegation can call declared CLIs or a configured gateway), and focuses on durable handoffs with next steps and dead ends ([guide](docs/guides/keep-decisions-without-background-ai.md)).

## Compatibility

| Assistant | Status | Test proof |
|---|---|---|
| Claude Code | supported, tested live on macOS | CI-tested |
| Codex | supported, tested live on macOS | CI-tested |
| Cursor | supported, fixture-tested; live reports welcome | CI-tested |
| Copilot (VS Code) | supported, fixture-tested; live reports welcome | CI-tested |
| Gemini CLI | supported, fixture-tested; live reports welcome | CI-tested |
| Antigravity | Preview, fixture-tested; rules, MCP, SessionStart/PreToolUse hooks; no automatic capture | CI-tested |

Testers on Cursor, Copilot (VS Code), Gemini CLI, or Antigravity: please share problems through [Something broke](https://github.com/Alenroyfeild/ai-dev-workspace/issues/new?template=bug.yml).

## Known limits

- **Client coverage:** Claude Code and Codex are live-tested on macOS; Linux and Windows are CI-tested only. Cursor, Copilot (VS Code), Gemini CLI, and Antigravity are fixture-tested.
- **Capture is best-effort:** Explicit CLI commands (`ws remember`, `ws checkpoint`) are deterministic; automatic transcript cue-word capture is best-effort.
- **Guards are a safety net:** Pattern matching blocks common risky commands and secrets in commands or written files, but is not an unbypassable security boundary.
- **Team sharing:** Multi-user flow tested on one Mac over a local HTTPS Git server: three separate profiles, sharing in both directions, generated Claude Code and Codex hook output. A hosted GitHub check and live assistant sessions are pending. ([Roadmap](docs/ROADMAP.md))

## Privacy & safety

- **Private by default:** Memory is stored outside checkout paths in `~/.ai-dev-workspace/<repo-name>`. Team sharing requires an explicit private repo (`ws team init`) with manual confirmation.
- **Redaction is best-effort:** `ws` masks known API keys, tokens, and private spans (`<private>...</private>`), but regex redaction is best-effort and does not replace operational secret hygiene.
- **Guards are a safety net:** The `guards` PreToolUse hook blocks known risky shell patterns and secrets in commands or written files, but it is a safety net, not an unbypassable security boundary.

## Coming next

- **Common Agent Plugins manifest (PLG3):** parked and unavailable until Codex can load the root manifest without losing plugin hooks.
- **Repo discovery through MCP roots (PLG5):** parked and unavailable; codex-cli 0.155.1 offers no roots and cannot expand plugin MCP paths. Use `ws start` for MCP.

## Documentation

- **Start:** [5-minute tutorial](docs/TUTORIAL.md) · [Setup guide](docs/SETUP.md) · [Demo walkthrough](docs/DEMO.md) · [Cross-client guide](docs/guides/share-memory-claude-code-codex.md)
- **Use:** [CLI commands](docs/COMMANDS.md) · [Packs catalog](docs/PACKS.md) · [Skills distribution](docs/SKILLS.md) · [MCP server](docs/MCP.md) · [Advanced usage](docs/ADVANCED.md)
- **Guides:** [Keep decisions without background AI](docs/guides/keep-decisions-without-background-ai.md) · [Stop retrying dead ends](docs/guides/stop-retrying-failed-approaches.md)
- **Team:** [Team use](docs/TEAM.md) · [Team workspace setup](docs/TEAM-WORKSPACE.md)
- **Reference:** [Overview](docs/OVERVIEW.md) · [Architecture](docs/ARCHITECTURE.md) · [Benchmark measurements](docs/MEASUREMENTS.md) · [Client verification](docs/CLIENT-VERIFICATION.md) · [Windows support](docs/WINDOWS.md) · [Roadmap](docs/ROADMAP.md)

## Status & contributing

`ai-dev-workspace` is in public beta (v0.1.0-beta.6 on PyPI). Planned improvements are tracked in the [Roadmap](docs/ROADMAP.md). Bug reports and feedback are welcome through [Something broke](https://github.com/Alenroyfeild/ai-dev-workspace/issues/new?template=bug.yml).

Released under the [MIT License](LICENSE). <!-- mcp-name: io.github.Alenroyfeild/ai-dev-workspace mcp-name: io.github.alenroyfeild/ai-dev-workspace -->
