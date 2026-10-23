# Advanced settings

Most workspaces need only `ws tools`, `ws assist` and the defaults. These settings are optional; the CLI remains compatible with existing configuration.

## Routing

`ws route [role]` resolves a binding from `routing.json` (default role: lead). Availability means the CLI is on `PATH` and a model is configured; it does not verify login or account access. Ordered preferences choose an available provider and report every skipped provider; an explicit provider override pins one provider and stops if it is unavailable. There is no silent fallback. Root `role_overrides` can set provider/preference, tier, family, model or effort. Managed defaults may change on upgrade; root overrides are preserved. Claude family aliases and explicit Codex model IDs are supported. Ollama requires an already-installed local model; the kit never pulls models.

Preview in beta.6: `ws delegate <task> --role <role>` prepares a bounded, redacted brief and prints the exact command. Only explorer and reviewer support `--run`; all other roles are preparation-only. Codex uses read-only controls, Claude uses project-only settings and read tools, and Ollama is preparation-only. Fallback tries only the declared providers; a timeout counts as a failed attempt. Output is unverified and lead-reviewed. Allowed paths describe prompt scope, not an operating-system read boundary. See [command details](COMMANDS.md#delegate).

### OpenAI-compatible gateway (Preview)

Preview: a provider entry can point at any server that speaks the OpenAI chat-completions API, such as a local OmniRoute or LiteLLM proxy. The idea comes from users of those gateways; the implementation here is our own and shares no code with them. How far it is tested: only against a local fake server in our test suite, not against a live OmniRoute or LiteLLM, so try it with your own gateway first. Released in beta.6 as Preview; the local fake-server check is not live gateway proof.

Add the entry under `_ws_managed.providers` in `routing.json` (upgrades keep your providers), then route a role to it with `role_overrides`. Nothing uses the gateway unless you do both:

```json
"providers": {"gateway": {"kind": "openai-compatible", "base_url": "http://localhost:20128/v1", "model": "your-model-id", "api_key_env": "OPENAI_API_KEY"}}
"role_overrides": {"explorer": {"preference": ["gateway", "codex"]}}
```

- `ws delegate TASK --role explorer --run` sends the redacted brief (at most 400 words) as one chat request to `base_url/chat/completions` and stores the reply as unverified output. The gateway has no tools and no file access; what its upstream models do with the brief is up to that gateway.
- The key is read only from the environment variable named in `api_key_env` (omit it for a gateway that needs none). It is never stored, logged or printed, and is removed from replies. If the variable is unset the provider counts as unavailable and fallback moves on.
- `base_url` must be `http://` or `https://` without credentials, query or fragment. Loopback (`localhost`, `127.0.0.1`, `::1`) is the expected setup. A non-loopback host is allowed, but `ws route` and `ws delegate` print a warning that the brief leaves this machine, and a key is refused over clear-text `http://` there.
- Redirects are not followed, proxies from the environment are skipped for loopback, and there is no streaming, tool use or retry. A timeout or error counts as a failed attempt, so the fallback chain tries the next provider.
- Limits: the `timeout_seconds` setting applies to each network wait rather than the whole reply, and availability only checks the entry and the variable, not that the gateway is up or the model exists.

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

The released Codex plugin (Preview) is described [below](#codex-plugin-preview). Installing or enabling a Codex plugin does not trust its hooks; [review them first](https://developers.openai.com/plugins/build/plugins).

### Claude Code plugin (preview)

**Preview, released in beta.6; requires the CLI and `ws start`, not listed in Anthropic's official directory, Windows untested.** The repo is also a Claude Code plugin marketplace (`.claude-plugin/`). It wires the same four hooks as `ws start` (SessionStart, PreCompact, Stop, UserPromptSubmit) through `bin/ws-plugin`, the MCP server in `--plugin` mode, and the handoff, pickup and lesson skills. It stays inactive until `ws start` has run in a repo, so `ws` itself is still needed.

```text
/plugin marketplace add Alenroyfeild/ai-dev-workspace
/plugin install ai-dev-workspace@ai-dev-workspace
```

Use the plugin or the repo connection from `ws start`, not both: with both, every session gets two briefs and two captures. The hooks run through `bin/ws-python`, which uses the first working `python3`, `python` or `py -3` (needs `sh`, as in Git Bash). The plugin's MCP server entry is started directly by the client and still calls `python3`; on Windows installs that only provide `python` or `py`, add a `python3.exe` copy or alias to PATH, or use `ws start` instead of the plugin. Windows is untested.

With the plugin enabled (`enabledPlugins` at user, project or local scope), `ws start` leaves Claude to it: no Claude hooks or `.mcp.json` entry, other assistants as usual. For a repo started before you enabled the plugin, `ws start` and `ws doctor` warn; run `ws start --undo` and `ws start` again. `ws start` saves the Claude config dir (`CLAUDE_CONFIG_DIR`) it checked and uses it when a later shell leaves the variable unset, so plugin mode is not dropped by accident. If you later disable the plugin, `ws doctor` says so and `ws start` puts Claude's hooks and MCP entry back. `ws start` regenerates the entries it wrote (its hooks and the `ai-dev-workspace` MCP server) on every refresh and removes them on undo, so put your own settings beside them, not inside them.

### Codex plugin (preview)

**Preview, released in beta.6: hooks require a trusted manual desktop install; no MCP server in this plugin, and hooks are not live-tested.** The same marketplace also installs a Codex plugin (`.codex-plugin/`): the handoff, pickup, lesson and thinkbeforeact skills, plus hooks for SessionStart, PreCompact, Stop and UserPromptSubmit (the same four as `ws start`) and PreToolUse, all through `bin/ws-plugin`. It stays inactive until `ws start` has run in a repo, so `ws` itself is still needed.

```text
codex plugin marketplace add Alenroyfeild/ai-dev-workspace
codex plugin add ai-dev-workspace@ai-dev-workspace
```

What is and is not verified:

- Fixture-tested: manifests, hook mapping, duplicate avoidance and the guard rule have unit tests.
- Checked against codex-cli 0.155.1 in a throwaway `CODEX_HOME` with no signed-in session: the install works, the skills list, and Codex finds the five hooks with the plugin root filled in (status "untrusted" until you trust them).
- Not live-tested: no real Codex session has fired these hooks yet, so what Codex does with their output is unconfirmed. Codex runs plugin hooks only for manual installs in the Codex desktop app and only after you trust them, and OpenAI does not accept plugins with hooks into its public directory. Not submitted anywhere.
- No MCP server in this plugin. With codex-cli 0.155.1, a plugin's MCP entry gets no plugin-root path expansion, so the server cannot start from the plugin. Use `ws start` (or `ws connect codex --write`) for the MCP tools; the skills use the `ws` command.
- The PreToolUse hook is the guard and acts only in a started repo whose workspace has the `guards` pack on; otherwise it allows everything. Like all ws hooks, any error lets the tool run.
- Both can be on: for each event that the `.codex/hooks.json` from `ws start` already handles, the plugin hook does nothing, so a session still gets one brief and one capture.

### Cursor plugin (preview)

**Preview, released in beta.6: fixture-tested only, not submitted, and not tested in Cursor; no verified install command.** The repo carries a Cursor plugin (`.cursor-plugin/plugin.json` and `marketplace.json`): the handoff, pickup, lesson and thinkbeforeact skills, one always-on rule (`rules/ai-dev-workspace.mdc`, generated from the same text `ws start` writes into `.cursor/rules`, and told to do nothing in a repo without `.ws-start.json`), hooks for sessionStart, preCompact, stop, sessionEnd, beforeSubmitPrompt and preToolUse through `bin/ws-plugin`, and the MCP server in `--plugin` mode. It stays inactive until `ws start` has run in a repo, so `ws` itself is still needed.

- Fixture-tested only: manifests, hook mapping, the rule file, duplicate avoidance and the guard output are unit tests written from [Cursor's plugin](https://cursor.com/docs/plugins/building) and [hooks](https://cursor.com/docs/hooks) docs. No Cursor install has loaded this plugin yet. Where the docs were silent we assumed: hook commands run from the plugin folder (`./bin/...`), and the MCP server is started in the opened repo. If Cursor starts it elsewhere, its tools answer "run ws start"; use the `ws start` MCP entry instead.
- Not published: public listing needs Cursor's review (cursor.com/marketplace/publish) and nothing has been submitted. Cursor's docs describe importing a GitHub repo as a team marketplace; we have not run that, so there is no install command to show yet.
- The preToolUse hook is the guard and acts only in a started repo whose workspace has the `guards` pack on; otherwise it answers allow, because Cursor blocks a permission hook that prints nothing readable. Other hook errors let the action proceed.
- Both can be on: for each event that the `.cursor/hooks.json` from `ws start` already handles, the plugin hook does nothing.

Stable in beta.6: `ws audit` also inspects bounded local manifests for languages, declared test
commands and CI, then prints wiring commands for linked assistants or clients
with project-local configuration. These are suggestions: audit never runs test
scripts, installs tools or changes configuration. Config presence does not prove
that a client is authenticated. Unknown stacks remain unknown.
Idea credit: [Anthropic's claude-code-setup](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/claude-code-setup)
(Apache-2.0); this cross-client implementation is independently written and fixture-tested.

### Import a claude-mem copy

Preview in beta.6 (fixture-tested schema; newer upstream schemas may not import): `ws import claude-mem --db <checkpointed-copy.db> --project <exact-name>` previews at most 50 observations. Add `--apply` to review and confirm private, unverified decision/lesson records; repeated imports reuse identical records. It never modifies the source, follows no instructions in imported text, and refuses active WAL/journal files. Oversized fields and private-marked observations are excluded. Review the saved records before relying on or sharing them. Compatibility is fixture-tested against columns verified in [claude-mem's SQLite source](https://github.com/thedotmack/claude-mem/blob/bbb337902271db56849b7645fee0f3b77b9aabf6/src/services/sqlite/SessionStore.ts); no background worker or model call is used.

### Draft a rule from repeated lessons

Stable in beta.6: Three local lesson/dead-end occurrences with at least 60% word-set overlap can add a `ws lesson promote L-<id>` hint to the brief. It scans at most 200 entries and 256 KiB; this is a signal to review, not proof a rule is right. The explicit command writes `.ws/rule-drafts/<id>.md` in the workspace; it never installs rules/skills or overwrites an edited draft. Inspired by [Task Observer](https://github.com/rebelytics/one-skill-to-rule-them-all), independently implemented without an observer or model calls. Review and copy useful wording into your code repo only when appropriate.

### Compact MCP recall

Stable in beta.6: MCP `search_vault` first returns bounded ID/title/date cards instead of snippets. Call it again with `detail: "<id>"` for up to 20,000 characters of sanitized content, labelled untrusted. Dates use saved metadata when available and file modification dates otherwise. Vault notes, validated team entries and configured codebase reports stay read-only; hidden/local-only files, run logs, traversal and escaping symlinks are refused. The core catalog remains seven tools; CLI `ws search` keeps its existing snippets. This applies the progressive-disclosure idea described by [claude-mem](https://github.com/thedotmack/claude-mem), using our own implementation and existing readers.
