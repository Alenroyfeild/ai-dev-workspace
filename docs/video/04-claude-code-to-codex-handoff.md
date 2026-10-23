---
title: Claude Code to Codex handoff
duration_hint: 45s
status: Stable
ws_version: 0.1.0b5
---
## Problem
Switching between Claude Code and Codex mid-task loses active decisions and requires re-explaining context.
## Steps
```sh
ws start --yes
ws remember "Use integer cents for currency calculations"
ws checkpoint --status in_progress --next "Write migration 0002" --note "Handoff=Schema drafted, pending test"
ws brief --client codex
ws start --undo
```
## Guidance
Stable: Claude Code and Codex share the exact same local Markdown task record outside git (`~/.ai-dev-workspace/<repo-name>`).
Explicit decisions saved with `ws remember` and next actions saved with `ws checkpoint` appear in the next session's brief.
Limits:
Automatic cue-word capture from session transcripts is best-effort; explicit CLI commands are deterministic.
Both Claude Code and Codex are live-tested on macOS and CI-tested on Linux and Windows in released beta.5.
Task memory provides prompt context; an assistant can still ignore brief advice if instructed otherwise.
This lesson shows the brief Codex receives from the CLI; it is not a recording of a live Codex session.
## Narration
When you switch between Claude Code and Codex mid-task, you should not have to re-explain earlier architectural choices. Running `ws start` connects your repository to private Markdown memory outside git. When you record a decision with `ws remember` and save your next action with `ws checkpoint`, both assistants see it at their next session start. Opening Codex in the same project injects the saved decision and next step into context at session start. Running `ws start --undo` cleanly removes assistant configuration without losing your saved notes.
