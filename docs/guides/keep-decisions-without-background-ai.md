# Keep decisions across Claude Code sessions without a background AI

Each new Claude Code session starts without the last one's decisions. Two tools solve this differently: [claude-mem](https://github.com/thedotmack/claude-mem) and `ai-dev-workspace`. Pick on how you want memory made, not on a scoreboard.

## How they differ

**claude-mem** (Apache-2.0, per its README) captures tool usage through lifecycle hooks (SessionStart, PostToolUse, Stop and others), compresses it with AI into summaries, and stores sessions and observations in SQLite with full-text search plus a Chroma vector database for semantic search. It has a local web viewer and optional cloud sync. Its README lists Claude Code, Codex, Gemini and several other clients.

**ai-dev-workspace** keeps only what is written explicitly: decisions, the next action, blockers and dead ends, as plain Markdown outside your repo. It makes no model calls of its own ([Concepts](../CONCEPTS.md)). A short brief is injected at session start in Claude Code, Codex and the other connected assistants. Hooks can also capture cue-word decisions, but those are redacted, unverified and best-effort ([Commands](../COMMANDS.md)).

## Try the explicit way

```sh
HOME=$(mktemp -d) sh -c 'cd $(mktemp -d) && git init -q && ws start --yes && ws remember "Prices are integer cents" && ws checkpoint --status in_progress --next "Add the rate limit to /login" && ws brief'
```

This uses a throwaway HOME and repo. In your own repo run `ws start` (it previews first), then the `remember`, `checkpoint` and `brief` lines. The next session, in any connected assistant, starts with the brief:

```text
Explicit Handoff (saved task record): Decision: Prices are integer cents
Next action: Add the rate limit to /login
```

Remove everything with `ws start --undo`.

## Bring claude-mem observations over

Already use claude-mem? Make a checkpointed copy of its SQLite file (the importer refuses active WAL or journal files), then preview:

```sh
ws import claude-mem --db ./claude-mem-copy.db --project my-project
ws import claude-mem --db ./claude-mem-copy.db --project my-project --apply
```

The first command only previews up to 50 observations. `--apply` asks before saving them as private, unverified decision and lesson records. The source is never modified and imported text is not treated as instructions. Review the records before relying on them ([details](../ADVANCED.md#import-a-claude-mem-copy)).

## When to choose which

| You want | Better fit |
|---|---|
| Automatic recall of what happened, without writing anything down | claude-mem |
| Semantic search across a large history | claude-mem |
| Decisions you can read, diff and edit by hand | ai-dev-workspace |
| No extra model usage or vector store for memory | ai-dev-workspace |
| A handoff with a next action and dead ends across assistants | ai-dev-workspace |

They can run side by side: the importer above is the bridge, and neither replaces the other's strengths.

## Limits

- ai-dev-workspace only remembers what is saved. If nobody runs `ws remember` or `ws checkpoint`, automatic capture is best-effort.
- The published benchmark covers decisions given in conversation, Claude Code to Claude Code and Claude Code to Codex. It did not compare against claude-mem ([Measurements](../MEASUREMENTS.md)).
- The import is fixture-tested against claude-mem's SQLite columns, not against every version.
