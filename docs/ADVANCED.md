# Advanced settings

Most workspaces need only `ws tools`, `ws assist` and the defaults. These settings are optional; the CLI remains compatible with existing configuration.

## Routing

`ws route [role]` resolves a binding from `routing.json` (default role: lead). Availability means the CLI is on `PATH` and a model is configured; it does not verify login or account access. The first provider preference is authoritative, so an unavailable provider stops instead of silently falling back. Root `role_overrides` can set provider/preference, tier, family, model or effort. Managed defaults may change on upgrade; root overrides are preserved. Claude family aliases and explicit Codex model IDs are supported. Ollama requires an already-installed local model; the kit never pulls models.

`ws delegate <task> --role <role>` prepares a bounded, redacted brief and prints the exact command. Only explorer and reviewer support `--run`; all other roles are preparation-only. Codex uses read-only controls, Claude uses project-only settings and read tools, and Ollama is preparation-only. Output is unverified and lead-reviewed. Allowed paths describe prompt scope, not an operating-system read boundary. See [command details](COMMANDS.md#measure-and-maintain).

## Tool profiles and assist

`ws tools` is the explicit catalog for recommended, optional and caution tools. It reports availability and never installs anything. Set `tool_profile` in `workspace.json` to `lean` (core only), `standard` (recommended) or `full`; `tool_overrides` maps tool names to `on`, `off` or `ask`. These settings guide `ws doctor` and assist suggestions and never remove software. `ws tools --cost` estimates MCP schema bytes, skill/plugin metadata size and cached CodeBurn use.

`ws assist` offers up to two local workspace suggestions and asks before applying changes. `ws assist decide <id> accepted|declined|snoozed|always [--until YYYY-MM-DD]` stores permission in `.ws/assist.json`; declines are hidden for 30 days. `ws assist apply <id>` executes only accepted/always local map or trace actions. Other actions stay for review. Notices surface suggestions once per workspace. Cost analysis uses the daily CodeBurn cache and recent connector-use data; it excludes protected built-ins, the workspace server, Graphy-related tools, in-use servers and tools pinned `on`. It never runs `codeburn optimize --apply`; missing usage evidence suppresses connector advice.

## Usage import

`ws run import codeburn [--since YYYY-MM-DD] [--task ID]` reads local `codeburn.export.v2` records. Matches require canonical repository paths and task windows; ambiguous records are skipped. Input totals include cache reads/writes, and reasoning tokens are not counted twice. Re-importing a growing session updates its existing entry keyed by task, session, provider and model. Task text remains unchanged; run logs retain neither raw exports nor project paths. CodeBurn exports 30 days by default. See [the export implementation](https://github.com/getagentseal/codeburn/blob/main/src/export.ts).
