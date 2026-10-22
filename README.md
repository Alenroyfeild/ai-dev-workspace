# AI Dev Workspace

Switch between Claude Code and Codex without re-explaining your decisions. Your assistant remembers work between sessions in Markdown you own. It keeps decisions, the next step and what not to retry, and warns when files it names changed or disappeared. Try it before connecting a repo: `ws demo` · [5-minute tutorial](docs/TUTORIAL.md) · [remove it](docs/TUTORIAL.md#remove-it)
<!-- Demo GIF -->
## Quick start

```bash
pipx install ai-dev-workspace --pip-args='--pre'  # beta; omit --pip-args after a stable release
cd ~/code/myapp && ws start
```
No pipx? `brew install pipx`, or `python3 -m venv ~/.ws && ~/.ws/bin/pip install --pre ai-dev-workspace`; put its `bin` directory on `PATH` before `ws start`. Prefer a Claude Code plugin? See the [plugin preview](docs/ADVANCED.md#claude-code-plugin-preview).
## Example
```text
Session 1 — You: “Empty email returns missing_email; leave signup unchanged.”
Assistant: “I’ll trace login and keep the decision with this task.”
You: “Stop here; I’ll resume tomorrow.”
Session 2 — You: “Continue the login fix.”
Assistant: “The saved note says return missing_email and leave signup unchanged.”
You: “Yes, continue.”
```
## Results (small synthetic samples, not general productivity)
| Session 1 → session 2 | Without workspace | With workspace |
|---|---:|---:|
| Claude Code → Claude Code | 0/5 | **5/5** |
| Claude Code → Codex | 0/5 | **5/5** |
| Codex → Codex | 0/3 | **3/3** |

Later Codex → Codex runs (n=5 each) were less favourable: the workspace passed 1/5 and 2/5, while a plain `HANDOFF.md` control passed 4/5 and 5/5. See [bench/README.md](bench/README.md).
## Team sharing
Your notes stay private. Share only what you approve, and your teammates' assistants start with it: after `ws start`, `ws team init <private-repo> --attest-private` (`--yes` in scripts) · `ws know add "Payments API rejects floats" --category domain --team` · `ws sync`. A teammate runs `ws team link <private-repo>`; their next brief shows the note, labelled as shared team context, and their own decisions still win. [Team quick start](docs/TEAM-WORKSPACE.md#quick-start)
## Compatibility
| Client | macOS | Linux/Windows |
|---|---|---|
| Claude Code | supported, tested live on macOS | CI-tested |
| Codex | supported, tested live on macOS | CI-tested |
| Cursor | supported, fixture-tested; live reports welcome | CI-tested |
| Copilot (VS Code) | supported, fixture-tested; live reports welcome | CI-tested |
| Gemini CLI | supported, fixture-tested; live reports welcome | CI-tested |

Testers on Cursor, Copilot (VS Code), or Gemini CLI: please share problems through [Something broke](https://github.com/Alenroyfeild/ai-dev-workspace/issues/new?template=bug.yml). · [Overview](docs/OVERVIEW.md) · [Setup](docs/SETUP.md) · [Commands](docs/COMMANDS.md) · [Keeping corrections](docs/COMMANDS.md#save-a-correction) · [Measurements](docs/MEASUREMENTS.md) · [Client verification](docs/CLIENT-VERIFICATION.md) · [Skills](docs/SKILLS.md) · [Packs](docs/PACKS.md) · [Team use](docs/TEAM.md) · [Windows](docs/WINDOWS.md) · [Roadmap](docs/ROADMAP.md) · [License](LICENSE) <!-- mcp-name: io.github.Alenroyfeild/ai-dev-workspace mcp-name: io.github.alenroyfeild/ai-dev-workspace -->
