# Architecture

## Principles

1. **Plain files are the source of truth.** Markdown and JSON in a folder, versioned with git, readable without any tool. No database, no service to run.
2. **One implementation, many front doors.** `ws/core.py` holds all logic; the CLI (`ws/cli.py`), the MCP server (`mcp/server.py`) and tests call it. A new front door (an editor plugin, a web view) must also call `core`, never re-implement it.
3. **Provider-neutral.** Rules live in `AGENTS.md`, which every assistant reads. Provider-specific pieces (a Codex adapter, a Claude skill) live in packs and are optional.
4. **Load on demand.** Only `AGENTS.md` is always loaded (about 330 words plus pack snippets). Everything else is fetched by search, by section, or by digest.
5. **Deterministic first.** Counting, deduplication, shape extraction, validation and redaction are code, not model calls. Models are used for judgment.
6. **Prove, don't assume.** Capabilities that touch safety (sandboxing, write access) ship with a self-test that checks real effects on disk. Nothing is enabled on a claim.

## Layout

```text
ai-dev-workspace/            the kit (this repo)
  ws/core.py                 tasks, claims, knowledge, digest, run log, packs, doctor
  ws/cli.py, bin/ws          command line
  mcp/server.py              MCP stdio server over core
  template/                  copied into every new workspace
  packs/<name>/              pack.json + optional vault/, AGENTS.snippet.md, scripts
  skills/                    assistant skills (e.g. thinkbeforeact)
  tests/

<your workspace>/            created by ws init; lives in its own (private) repo
  workspace.json             name, packs, repos
  AGENTS.md, CLAUDE.md       rules every assistant reads
  .mcp.json                  MCP registration for Claude Code
  vault/                     Tasks, Product, Project, Runbooks, Analysis, Runs, Learnings, Feedback
  .ws/                       lock file (git-ignored)
```

## Coordination model

- **Claim** writes `claimed_by` + a random token into the task's frontmatter under an exclusive file lock; a second claim fails. Checkpoints and releases need the token.
- **Stale writes**: `read_task` returns a sha256; `checkpoint --expected-sha` rejects writes if the record changed since it was read.
- **Atomic writes**: temp file + fsync + rename; an interrupted write never leaves a half file.
- Claims do not expire. Before releasing someone else's claim, check that session has really stopped.

## Orchestration model

```text
user request
  → lead assistant (planner tier): find task, read lessons, think before act, plan
  → cheap workers for bounded jobs: deterministic tools > local model > second AI (read-only)
  → worker tier implements the approved plan (in the lead's own tool)
  → lead verifies evidence and reviews; only the lead accepts
  → checkpoint + lesson + run log
```

`ws run log` records each step (provider, model, tokens, seconds, result) in `vault/Runs/<task>.jsonl`; `ws run report` aggregates them. This is how the "spend once, reuse" claim is measured per team instead of assumed.

## Scaling and maintenance

- **New domain or tool** → a pack. The core never learns about iOS, Android or a specific AI vendor.
- **Pack contract** (`pack.json`): `name`, `version`, `kind` (domain | worker | editor), `description`, `requires` (each `cmd` or `app`, `why`, `install`, `optional`), optional `setup` and `selftest` scripts. `ws doctor` reads it; nothing else is needed for discovery.
- **Versioned formats**: `workspace.json` has `schema_version`; migrations will go in `core` keyed on it.
- **Third-party pins**: worker packs pin exact upstream versions and verify a hash before patching. An upstream change means re-running the self-test, never silently trusting it.
- **Tests guard invariants**, not counts: one-writer claims, stale-write rejection, redaction, MCP protocol replies, pack idempotence, and regressions for every bug found.
