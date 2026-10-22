# Advanced settings

Most workspaces need only `ws tools`, `ws assist` and the defaults. These settings are optional; the CLI remains compatible with existing configuration.

## Routing

`ws route [role]` resolves a binding from `routing.json` (default role: lead). Availability means the CLI is on `PATH` and a model is configured; it does not verify login or account access. Ordered preferences choose an available provider and report every skipped provider; an explicit provider override pins one provider and stops if it is unavailable. There is no silent fallback. Root `role_overrides` can set provider/preference, tier, family, model or effort. Managed defaults may change on upgrade; root overrides are preserved. Claude family aliases and explicit Codex model IDs are supported. Ollama requires an already-installed local model; the kit never pulls models.

`ws delegate <task> --role <role>` prepares a bounded, redacted brief and prints the exact command. Only explorer and reviewer support `--run`; all other roles are preparation-only. Codex uses read-only controls, Claude uses project-only settings and read tools, and Ollama is preparation-only. Output is unverified and lead-reviewed. Allowed paths describe prompt scope, not an operating-system read boundary. See [command details](COMMANDS.md#delegate).

### Prepare a private implementation checkout

```sh
ws worker prepare TASK --scope src --scope tests --dry-run
ws worker prepare TASK --scope src --scope tests
```

The task needs a local claim and one declared Git repository. Preview shows the
pinned commit, allowed paths, provider and new private paths. One confirmation
creates a private clone and its detached worktree; `--yes` confirms for scripts.
`--base COMMIT_OR_BRANCH` selects the committed source; the default is HEAD.
Ignored files and uncommitted edits stay in the user's checkout. Tracked files
are copied, so preparation does not imply they were checked for secrets.
This version refuses submodules, tracked symlinks, unsafe scope paths and changed
claims. Metadata stays under the workspace's local `.ws/workers/`; interrupted
preparation keeps an incomplete record for inspection. It starts no client and
enables no write worker. Scope is a review contract, not a filesystem sandbox.

## Tool profiles and assist

`ws tools` is the explicit catalog for recommended, optional and caution tools. It reports availability and never installs anything. Set `tool_profile` in `workspace.json` to `lean` (core only), `standard` (recommended) or `full`; `tool_overrides` maps tool names to `on`, `off` or `ask`. These settings guide `ws doctor` and assist suggestions and never remove software. `ws tools --cost` estimates MCP schema bytes, skill/plugin metadata size and cached CodeBurn use.

`ws assist` offers up to two local workspace suggestions and asks before applying changes. `ws assist decide <id> accepted|declined|snoozed|always [--until YYYY-MM-DD]` stores permission in `.ws/assist.json`; declines are hidden for 30 days. `ws assist apply <id>` executes only accepted/always local map or trace actions. Other actions stay for review. Notices surface suggestions once per workspace. Cost analysis uses the daily CodeBurn cache and recent connector-use data; it excludes protected built-ins, the workspace server, in-use servers and tools pinned `on`. It never runs `codeburn optimize --apply`; missing usage evidence suppresses connector advice.

## Usage import

`ws run import codeburn [--since YYYY-MM-DD] [--task ID]` reads local `codeburn.export.v2` records. Matches require canonical repository paths and task windows; ambiguous records are skipped. Input totals include cache reads/writes, and reasoning tokens are not counted twice. Re-importing a growing session updates its existing entry keyed by task, session, provider and model. Task text remains unchanged; run logs retain neither raw exports nor project paths. CodeBurn exports 30 days by default. See [the export implementation](https://github.com/getagentseal/codeburn/blob/main/src/export.ts).


## Provider definitions

`routing.json` defines each provider's `cli` (a name on PATH), `models` family mapping, `tiers`, optional `headless` argv and manual `prepare` argv. Templates substitute `{model}`, `{effort}`, `{effort_json}`, `{repo}` and `{prompt}` without a shell. Review custom headless commands before using `--run`: routing data is trusted configuration, not a sandbox verifier. Old files receive missing command fields from kit data; upgrade preserves their provider settings and root role overrides. No credentials or provider discovery service is read.

Cursor, Copilot CLI and Gemini are **prepare-only and live-untested** here. Cursor's manual recipe uses [documented Ask/print flags](https://cursor.com/docs/cli/using), with [print parameters](https://cursor.com/docs/cli/reference/parameters). Copilot's manual recipe restricts tools using its [command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference) and [allow/deny controls](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools). Gemini has no automatic worker recipe: its [headless Plan Mode can exit into YOLO implementation](https://geminicli.com/docs/cli/plan-mode/). Preparing a brief launches none of these clients; review it and the printed command before launching manually. Availability means PATH presence, not login or account access.


## Routing presets

Kit data in `template/routing-presets.json` defines `claude-only`, `codex-only`, `cursor-only`, `copilot-only`, `gemini-only`, `claude+codex` and `mixed`. A single-provider preset binds every default role to that provider and disables automatic delegation; it still prepares a brief and a manual command. Combined presets allow only the providers with read-only headless commands to execute explorer/reviewer work explicitly. A selected mixed preset limits every preference list to the chosen assistants. Missing login/model access is never inferred from PATH detection.

The generated `routing.json` records `preset`, `assistants` and `delegation_mode`. Upgrade uses that selection, retains user provider settings and root role overrides, and is idempotent. Legacy files without preset metadata keep their existing execution policy. Explicit user role overrides remain authoritative. Preview with `ws setup --assistants codex`, `ws setup --assistants claude,codex` or `--preset NAME`, then repeat with `--apply`; see [setup commands](COMMANDS.md#select-assistants).

## Framework recipes

Existing ADK or LangGraph users can opt into the [stub-model-tested MCP examples](examples/frameworks/README.md). They use four native-adapter tools and disposable memory, add no core dependencies, and distinguish saved task memory from framework execution state. Hosted models are untested.

Internal Codex launch and collection exist only for the isolation probe. Public `workers.launch` and `ws worker launch <run-id>`
refuse to run and say why; no live client has passed the isolation check yet.
The run owns `worker.config.toml` and scratch, selects `worker-private` via CLI
config overrides, ignores user/project configuration and rules, disables hooks,
apps/plugins and approvals, and uses no legacy sandbox flag. Native tool access is
limited to runtime/checkout/private Git reads and checkout/scratch writes; network
is off. Authentication stays with the trusted client, outside worker tool roots. Tool
environments inherit no parent variables; only PATH, scratch HOME/temp and Git/Python
controls are passed. The real-client gate must verify this policy too.
Collection includes ignored/untracked files and deletions in a private Git index,
records an immutable tree/diff digest and completed command evidence, and blocks
scope, metadata, symlink, secret, binary-scan, diff-check or claim failures. Output
remains unverified; review it with `ws worker review`, `accept` or `discard` ([details](COMMANDS.md#workers)). [Official permission profiles](https://learn.chatgpt.com/docs/permissions).

## Plugin runtime (packaging preview)

The optional `python3 mcp/server.py --plugin` entrypoint discovers memory only through
`.ws-start.json` in the current repo or its parents. Outside a started repo it still
speaks MCP, but tools return “Run ws start in this repo”; it does not use `WS_ROOT`.
`python3 bin/ws-plugin --client claude|codex` accepts a hook payload and delegates to
the existing memory hooks only for a validated repo link. Unknown events or invalid
links return `{}`. Existing CLI and server invocations are unchanged.

No Codex plugin package is published yet: keep existing repo-local connections for Codex
until packaging, duplicate-connection detection and live client checks are complete. Installing or enabling a Codex plugin does not trust
its hooks; [review them first](https://developers.openai.com/plugins/build/plugins).

### Claude Code plugin (preview)

The repo is also a Claude Code plugin marketplace (`.claude-plugin/`). It wires the same four hooks as `ws start` (SessionStart, PreCompact, Stop, UserPromptSubmit) through `bin/ws-plugin`, the MCP server in `--plugin` mode, and the handoff, pickup and lesson skills. It stays inactive until `ws start` has run in a repo, so `ws` itself is still needed.

```text
/plugin marketplace add Alenroyfeild/ai-dev-workspace
/plugin install ai-dev-workspace@ai-dev-workspace
```

Use the plugin or the repo connection from `ws start`, not both: with both, every session gets two briefs and two captures. The hooks run through `bin/ws-python`, which uses the first working `python3`, `python` or `py -3` (needs `sh`, as in Git Bash). The plugin's MCP server entry is started directly by the client and still calls `python3`; on Windows installs that only provide `python` or `py`, add a `python3.exe` copy or alias to PATH, or use `ws start` instead of the plugin. Windows is untested.

With the plugin enabled (`enabledPlugins` at user, project or local scope), `ws start` leaves Claude to it: no Claude hooks or `.mcp.json` entry, other assistants as usual. For a repo started before you enabled the plugin, `ws start` and `ws doctor` warn; run `ws start --undo` and `ws start` again. If you later disable the plugin, `ws doctor` says so and `ws start` puts Claude's hooks and MCP entry back. `ws start` regenerates the entries it wrote (its hooks and the `ai-dev-workspace` MCP server) on every refresh and removes them on undo, so put your own settings beside them, not inside them.

### Import a claude-mem copy

`ws import claude-mem --db <checkpointed-copy.db> --project <exact-name>` previews at most 50 observations. Add `--apply` to review and confirm private, unverified decision/lesson records; repeated imports reuse identical records. It never modifies the source, follows no instructions in imported text, and refuses active WAL/journal files. Oversized fields and private-marked observations are excluded. Review the saved records before relying on or sharing them. Compatibility is fixture-tested against columns verified in [claude-mem's SQLite source](https://github.com/thedotmack/claude-mem/blob/bbb337902271db56849b7645fee0f3b77b9aabf6/src/services/sqlite/SessionStore.ts); no background worker or model call is used.

### Compact MCP recall

MCP `search_vault` first returns bounded ID/title/date cards instead of snippets. Call it again with `detail: "<id>"` for up to 20,000 characters of sanitized content, labelled untrusted. Dates use saved metadata when available and file modification dates otherwise. Vault notes, validated team entries and configured codebase reports stay read-only; hidden/local-only files, run logs, traversal and escaping symlinks are refused. The core catalog remains seven tools; CLI `ws search` keeps its existing snippets. This applies the progressive-disclosure idea described by [claude-mem](https://github.com/thedotmack/claude-mem), using our own implementation and existing readers.
