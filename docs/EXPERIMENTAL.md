# Experimental features

Experimental means: ships, but outside the 1.0 promise; the test level shown is today's.

Expect changes and gaps. Decision recorded 2026-11-12. Each line gives the label the feature carried in the README until now and its limit, copied from the README and docs; where a feature has no README label, the row says so. The 1.0 promise itself is in the [README](../README.md).

## Delegation, workers and routing

| Feature | Label until now | Limit | Docs |
|---|---|---|---|
| Delegation (`ws delegate`), workers (`ws worker`), routing (`ws route`), orchestration | No README label; listed under "Advanced and experimental" in COMMANDS.md | `ws delegate --run` starts only declared assistant CLIs or sends a redacted brief to an explicitly configured gateway; output is unverified. Write workers cannot be launched in this version (design note) | [Commands](COMMANDS.md#advanced-and-experimental), [Advanced](ADVANCED.md#routing), [Orchestration note](AGENT-ORCHESTRATION.md) |
| Worker fallback chain | Preview | Only declared providers and read-only roles run; timeout is a failed attempt | [Advanced](ADVANCED.md#routing) |
| Gateway provider | Preview | Local fake-server tests only; sends a redacted brief to configured base_url, without tools | [Advanced](ADVANCED.md#openai-compatible-gateway-preview) |

## Packs, imports and analysis

| Feature | Label until now | Limit | Docs |
|---|---|---|---|
| `ws audit` | Stable | Read-only stack/wiring suggestions from bounded local manifests; no login or live-client proof | [Commands](COMMANDS.md#daily-use) |
| `ws import claude-mem` | Preview | Fixture-tested SQLite copy import; newer upstream schemas may not import | [Advanced](ADVANCED.md#import-a-claude-mem-copy) |
| `ws digest` (digest pack) | Stable | Summarizes logs or JSON; focus scans the first 4096 characters per line | [Commands](COMMANDS.md#search-and-lessons) |
| Discipline pack | Stable | Advisory nudge when the same command fails repeatedly in a session | [Packs](PACKS.md) |
| MCP Registry | Preview | Pre-configured `server.json` catalog entry for MCP client discovery | [MCP](MCP.md) |
| `digest_file` MCP tool | Preview | Opt-in size-only advice; scoped file summaries, no automatic compression | [Packs](PACKS.md#optional-digest-advice) |
| Behavior pack | Stable | Opt-in engineering guidelines; advice, not enforcement or learned session patterns | [Packs](PACKS.md#behavior-guidelines) |
| Lesson promotion | Stable | Repeated-note similarity suggests a draft; no automatic rule installation | [Advanced](ADVANCED.md#draft-a-rule-from-repeated-lessons) |

## Team sharing and plugins

| Feature | Label until now | Limit | Docs |
|---|---|---|---|
| Team sharing | Preview | Private git-backed knowledge repo with consent-based pulls and previews. Multi-user flow tested on one Mac over a local HTTPS Git server: three separate profiles, sharing in both directions, generated Claude Code and Codex hook output. A hosted GitHub check and live assistant sessions are pending | [Team](TEAM-WORKSPACE.md), [Roadmap](ROADMAP.md) |
| Codex plugin | Preview | Hooks need a trusted manual desktop install; no MCP; hooks not live-tested | [Advanced](ADVANCED.md#codex-plugin-preview) |
| Cursor plugin | Preview | Fixture-tested only; not submitted; no verified install command | [Advanced](ADVANCED.md#cursor-plugin-preview) |
| Codex SessionStart catch-up | Preview | Recovers changed transcript content for the claimed task; fixture-tested, not live-tested with Codex resume | [Advanced](ADVANCED.md#codex-sessionstart-catch-up) |
| MCP plugin roots discovery | Preview | Plugin server finds a `ws start` repo from client roots; Codex offers no roots | [Advanced](ADVANCED.md#plugin-runtime-packaging-preview) |

## Other assistants

No live session is on record for these, so they are fixture-tested only. Reports are welcome through [Something broke](https://github.com/Alenroyfeild/ai-dev-workspace/issues/new?template=bug.yml).

| Assistant | Status until now | Test proof |
|---|---|---|
| Cursor | supported, fixture-tested; live reports welcome | CI-tested |
| Copilot (VS Code) | supported, fixture-tested; live reports welcome | CI-tested |
| Gemini CLI | supported, fixture-tested; live reports welcome | CI-tested |
| Antigravity | Preview, fixture-tested; rules, MCP, SessionStart/PreToolUse hooks; no automatic capture | CI-tested |

See also [client verification](CLIENT-VERIFICATION.md).
