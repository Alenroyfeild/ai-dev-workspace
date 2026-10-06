# AI Dev Workspace  ·  beta

> **Beta (0.1.0-beta.1).** Works and is tested, but expect changes. Try it, and when something gets in your way your assistant will offer to send feedback: that is how this improves.

**Shared, durable memory and coordination for AI-assisted software development.**
Spend tokens once to learn your product and codebase; reuse that knowledge in every later session, with any assistant (Claude, Codex, Cursor or any MCP client).

AI coding assistants forget everything between sessions. Each new chat re-reads the same files, re-discovers the same product rules and repeats the same mistakes. AI Dev Workspace is a folder of plain Markdown plus a small CLI and an MCP server that give every assistant:

- **Task memory** – one record per ticket or branch: objective, evidence, blockers, exact next action. Any assistant can resume without the old chat.
- **Product and project knowledge** – verified facts and a codebase map, searched in snippets instead of re-read.
- **Lessons** – mistake → rule, checked before risky work so mistakes are not repeated.
- **Coordination** – claims (one writer per task), stale-write protection, checkpoints.
- **Token discipline** – deterministic log/JSON digests, load-on-demand rules, cheap workers for cheap jobs, and a per-step cost log so savings are measured, not assumed.
- **Feedback loop** – users record friction and ideas; the workspace improves from them.

Everything is optional and pluggable. The core needs only Python 3.9+ and git.

## Quick start (2 minutes)

With pipx available, install the isolated CLI with `pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace`. Templates, packs, skills and the MCP server are bundled. The clone-based setup below remains supported.

```bash
git clone https://github.com/Alenroyfeild/ai-dev-workspace.git ~/ai-dev-workspace
export PATH="$HOME/ai-dev-workspace/bin:$PATH"     # add to your shell profile
ws init ~/work/myapp-workspace --name myapp --pack obsidian --repo ~/code/myapp
cd ~/work/myapp-workspace
ws doctor                                          # what is installed, what to add
ws task new APP-123 "Fix login crash" --objective "Crash when email is empty"
```

Then open the workspace folder in your assistant (Claude Code, Codex, …). It reads `AGENTS.md` (about 250 words) and pulls everything else on demand. Full guide: [docs/SETUP.md](docs/SETUP.md).

## Packs (plug in only what you need)

| Pack | Kind | Adds | Needs |
|---|---|---|---|
| `obsidian` | editor | Vault settings so Obsidian opens the memory as a linked, searchable vault | [Obsidian](https://obsidian.md) (free, optional) |
| `local-llm` | worker | Free on-device log triage via Ollama | [Ollama](https://ollama.com) + a small model |
| `codex-worker` | worker | Codex as a **read-only** second AI over ACP, with a hostile self-test | Node, `acpx`, a Codex sign-in |
| `ios` | domain | iOS build triage, Simulator debugging, App Store review runbooks | Xcode (optional) |

`ws packs` lists them; `ws pack add <name>` plugs one into an existing workspace. Writing your own pack (Android, web, backend, data…) is a folder with a `pack.json`: see [docs/PACKS.md](docs/PACKS.md).

## Commands

| Command | Does |
|---|---|
| `ws init <dir> --name N [--pack P] [--repo R]` | create a workspace |
| `ws doctor` | installed tools, missing pack requirements, recommended extras |
| `ws task new/find/list/show` | task records (`show --section "Next action"` reads only what you need) |
| `ws claim` / `ws release` / `ws checkpoint` | ownership and progress, with stale-write protection |
| `ws search "<words>"` | ranked snippets from product, project, runbook and analysis notes |
| `ws lesson add/search` | lessons learned |
| `ws feedback add/list` | user feedback on the workspace |
| `ws digest <file>` | deterministic summary of a big log or JSON file |
| `ws run log` / `ws run report` | per-step orchestration log: provider, model, tokens, seconds, result |
| `ws validate` / `ws status` | health check / overview |
| `ws feedback submit N` | turn a feedback item into a GitHub issue (preview first, redacted) |
| `ws feedback sync` | tick feedback whose issue was closed |
| `ws update [--check]` | see what the new release changed / update the kit |

The same operations are exposed as MCP tools by `mcp/server.py` (`ws init` writes `.mcp.json` for Claude Code).

## How the assistants work together

One lead assistant decides, plans, reviews and accepts. Cheaper workers do bounded jobs: a second AI in read-only mode explores code, a local model triages logs, deterministic tools summarise files. Worker output is evidence to verify, never a decision. Every step can be logged with `ws run log`, and `ws run report` shows where tokens and time actually went. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Updates and feedback, handled by your assistant

You don't need to remember any of it. At the start of a session the assistant runs `ws notices` once (cached; at most one network check a day) and, only when there is something, tells you in one line and asks:

> "ai-dev-workspace 0.2.0 is available: faster search. Update now?"
> "Your reported issue #12 was fixed. Check the release?"
> "You noted 'search misses plurals' last week. Share it with the maintainers?"

When something in the workspace annoys you or fails, the assistant offers to note it as feedback. Nothing is updated, recorded or sent without your yes, and feedback is redacted and previewed first. Offline or private setup: `export WS_OFFLINE=1`.

## Status

Early (0.1). Core, MCP server and packs are tested (`python3 -m unittest discover -s tests`). Write access for second-AI workers is deliberately not offered yet: see [docs/ROADMAP.md](docs/ROADMAP.md) for why and what comes next. Feedback and packs welcome: [CONTRIBUTING.md](CONTRIBUTING.md). How feedback becomes issues and releases: [docs/MAINTAINING.md](docs/MAINTAINING.md).

## License

MIT. The `codex-worker` pack downloads and patches `@agentclientprotocol/codex-acp` (Apache-2.0) on your machine; nothing of it is redistributed here.
