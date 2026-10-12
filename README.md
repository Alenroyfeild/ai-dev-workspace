# AI Dev Workspace

An assistant can lose a decision between sessions, making it repeat work or undo a settled choice.
AI Dev Workspace keeps task notes in Markdown your assistant can read next time.

## Quick start

```bash
pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace
ws init ~/work/myapp-ws --repo ~/code/myapp
cd ~/work/myapp-ws && ws connect claude
ws task new APP-123 "Fix login crash" && ws claim APP-123
```

## Example

```text
Session 1 — You: “Empty email returns missing_email; leave signup unchanged.”
Assistant: “I’ll trace login and keep the decision with this task.”
You: “Stop here; I’ll resume tomorrow.”
Session 2 — You: “Continue the login fix.”
Assistant: “The saved note says return missing_email and leave signup unchanged.”
You: “Yes, continue.”
```

## Results

| Session 1 → session 2 | Without workspace | With workspace |
|---|---:|---:|
| Claude Code → Claude Code | 0/5 | **5/5** |
| Claude Code → Codex | 0/5 | **5/5** |
| Codex → Codex | 0/3 | **3/3** |

Small synthetic samples; they show decisions surviving between sessions, not general productivity.

## More

[Extended overview](docs/OVERVIEW.md) · [Setup](docs/SETUP.md) · [Commands](docs/COMMANDS.md) · [Measurements](docs/MEASUREMENTS.md) · [Client verification](docs/CLIENT-VERIFICATION.md) · [Packs](docs/PACKS.md) · [Team use](docs/TEAM.md) · [Windows](docs/WINDOWS.md) · [Roadmap](docs/ROADMAP.md) · [License](LICENSE)
