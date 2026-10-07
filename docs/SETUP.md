# Setup guide

Every step after 2 is optional. `ws doctor` tells you what is missing and how to install it.

## 1. Install the kit

For an isolated CLI, use `pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace`. This includes templates, packs, skills and the MCP server; generated client configs and hooks use the install's Python environment. `ws update` prints `pipx upgrade ai-dev-workspace` for this installation. It does not run pipx for you; `ws update --check` still checks release notes. A plain venv installation uses that venv's pip with the original source to update. The git-clone alternative follows:

```bash
git clone https://github.com/Alenroyfeild/ai-dev-workspace.git ~/ai-dev-workspace
echo 'export PATH="$HOME/ai-dev-workspace/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
ws --help
```

macOS, Linux and Windows. Requires Python 3.9+ and git. No pip packages.

## 2. Create a workspace

One workspace per product (it can serve several repos). `ws map` also links an existing `graphify-out/GRAPH_REPORT.md` and its top headings; `ws search` searches that report. The kit never runs Graphify. is pending review.

```bash
ws init ~/work/myapp-workspace --name myapp --repo ~/code/myapp --pack obsidian
cd ~/work/myapp-workspace && ws doctor
```

Keep the workspace in its own git repo (`git init`) so the memory is versioned. Put it in a private repo if it holds company knowledge.

Existing files are kept. Proposed kit content goes beside them as `.ws-new`; review and apply it manually. Existing sidecars are kept too.

## 3. Connect your assistant

Run `ws connect claude`, `ws connect cursor`, `ws connect codex`, `ws connect vscode`, or `ws connect gemini`. Project config collisions are staged as `.ws-new` and kept for review. Codex prints the exact global-config block; `ws connect codex --write` appends it with a backup, refusing conflicting entries. VS Code uses `.vscode/mcp.json`; Gemini CLI uses `.gemini/settings.json`. The managed `.github/copilot-instructions.md` and `GEMINI.md` pointers tell those clients to follow `AGENTS.md`; existing files are preserved and the proposed pointer is staged as `.ws-new`. `ws doctor` lists the connections and pointer files; `ws doctor --mcp` starts configured servers to check them. Approve the server in the client before using its tools.

| Capability | Claude Code | Codex | Cursor | Copilot | Gemini CLI |
|---|---|---|---|---|---|
| Rules | proven | proven | documented, untested | documented, untested | documented, untested |
| MCP tools | proven | proven | documented, untested | documented, untested | documented, untested |
| Hooks | proven | proven | documented, untested | not wired yet (client supports hooks) | documented, untested |
| Skills | proven | proven | not wired yet (client supports skills) | not wired yet (client supports skills) | not wired yet (client supports skills) |
| Automatic capture | proven | proven | documented, untested | not available | documented, untested |

Only Claude Code and Codex have been tested with rules, MCP tools, hooks and skills. Automatic capture is proven for Claude Code only. `documented, untested` means the client's docs support it and `ws connect` sets it up, but nobody has run it yet. `not wired yet` means the client supports the feature but the workspace does not install it for that client yet.

**Claude Code** – open the workspace folder. `CLAUDE.md` loads `AGENTS.md`; `.mcp.json` registers the MCP server. Claude Code asks once to approve the project MCP server; approve it (or check with `claude mcp list`). To work on code in another folder, add that folder as an additional working directory.

**Codex** – open the workspace folder; Codex reads `AGENTS.md`. For MCP tools, add to `~/.codex/config.toml`:

```toml
[mcp_servers.ai-dev-workspace]
command = "python3"
args = ["/path/to/ai-dev-workspace/mcp/server.py", "--root", "/path/to/myapp-workspace"]
```

**Any other MCP client** (Cursor, Windsurf, …) – use the same command and args as its stdio server config.

**Think-before-act skill (Claude Code)**:

```bash
mkdir -p ~/.claude/skills && ln -s ~/ai-dev-workspace/skills/thinkbeforeact ~/.claude/skills/thinkbeforeact
```

Start a new session; `/thinkbeforeact <request>` is then available. New skills only appear in sessions started after they are installed.

## 4. Optional: Obsidian (read the memory comfortably)

1. Install Obsidian from https://obsidian.md (free).
2. `ws pack add obsidian` (skip if you used `--pack obsidian`).
3. In Obsidian: *Open folder as vault* → choose `<workspace>/vault`.

You get links between notes, the graph view and full-text search. The assistants do not need Obsidian; it is for you.

## 5. Optional but recommended: Ollama (free local model)

Cheap mechanical jobs (log triage, extraction) can run on your machine at no token cost.

```bash
brew install ollama            # or see https://ollama.com/download
ollama serve &                 # or start the Ollama app
ollama pull qwen3.5:4b         # small model, ~3 GB; any small instruct model works
ws pack add local-llm
python3 ~/ai-dev-workspace/packs/local-llm/summarize.py build.log
```

The model only sees the deterministic digest, and its answer is checked against the source file.

## 6. Optional: Codex as a read-only worker

```bash
npm install -g acpx @openai/codex
codex login                    # sign in once
ws pack add codex-worker
~/ai-dev-workspace/packs/codex-worker/setup.sh      # installs the pinned adapter, adds the read-only mode
~/ai-dev-workspace/packs/codex-worker/selftest.sh   # must print SELFTEST OK before you use it
```

`selftest.sh` tries reads and seven kinds of writes (patch tool, shell, Python, absolute path, symlink, `../`) in a throwaway folder and checks the disk itself. **INCONCLUSIVE** means the worker never ran (usually an expired sign-in: run `codex login`). Use the lane only after **SELFTEST OK**.

## 7. Optional: a domain pack

`ws packs` lists them (e.g. `ios`). `ws pack add ios` adds runbooks and rules for that platform. Missing your domain? Write a pack: [PACKS.md](PACKS.md).

## Updates and feedback

Automatic: your assistant checks `ws notices` at session start and asks before updating or sharing anything. `ws tools` shows recommended, optional and caution tools; nothing installs automatically. Set `tool_profile` in `workspace.json` to `lean`, `standard` or `full`, and `tool_overrides` to per-tool `on`, `off` or `ask`. `ws tools --cost` measures MCP schemas, skill/plugin metadata and cached Codeburn use. `ws assist` asks before applying suggestions. Use `ws run import codeburn` to import local usage and update an existing entry when a session grows.

## Daily loop

Run `ws connect claude` once to link the kit skills into `~/.claude/skills`, or `ws connect codex` for `~/.agents/skills`. Existing names are kept; check the command's notice. Restart the client after connecting. With `ws` on PATH, Claude's `/handoff` saves the current task's next action, evidence and blockers, `/pickup` reads that task memory in a new session, and `/lesson` records a requested rule. In Codex, use `$handoff`, `$pickup`, and `$lesson` (or select them with `/skills`). These skills use the CLI without MCP. Init and MCP connection calls do not install global skill links.

New workspaces include Claude Code and Codex project hooks. Approve their hook definitions in the client. SessionStart injects `ws brief`; Claude Stop requests a checkpoint once when a claim is at least 30 minutes stale. Plain `ws nudge` is read-only. Stop/PreCompact capture cue-bearing user sentences and the last assistant summary/next step after tool use, redacted and capped at 150 words per dated Captured block in Handoff only. Each session replaces its own block; existing human text, Evidence and Next action stay intact. Capture requires exactly one locally owned, unfinished claim. Claude behavior is unchanged; Codex supports chat JSONL and persisted response-item JSONL, excluding injected context by its metadata. Missing/unreadable, oversized (50 MB) or unsupported transcripts are skipped. Captured text remains unverified; use the handoff skill for precise memory.

`ws connect cursor` adds project `.cursor/hooks.json`: sessionStart supplies additional context; stop, preCompact and sessionEnd capture from the provided transcript path. `ws connect gemini` currently adds lifecycle hooks only in `.gemini/settings.json`; rules/MCP connection is a separate setup step. SessionStart supplies context; AfterAgent captures each turn, with PreCompress/SessionEnd as additional opportunities. Gemini supports conversation JSON and append-only JSONL with content patches/rewinds; tool results and thoughts are excluded. Cursor/Gemini are documented and fixture-tested, not proven in their real clients. Cursor transcripts must be enabled; its sessionStart is fire-and-forget. Gemini SessionEnd/PreCompress are best-effort, so AfterAgent also saves. See [Cursor hooks](https://cursor.com/docs/hooks), [Gemini hooks](https://geminicli.com/docs/hooks/reference/), and [Gemini configuration](https://geminicli.com/docs/reference/configuration/). Other clients currently get rules plus MCP only, without automatic lifecycle memory in this kit.

`ws upgrade` updates recognized workspace hook commands for connected clients, preserves unrelated settings/handlers, and stages `.ws-new` proposals for ambiguous/unmarked hook files. Review proposed files and approve changed hooks again; disabled/untrusted hooks cannot capture. No global config is needed for lifecycle hooks.

For Codex, trust the workspace when prompted, then use `/hooks` to review and trust the generated `.codex/hooks.json`. Changed hook definitions need review again. A fresh session receives the saved next action and asks before starting it. See the current [Codex hooks docs](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks) and [skills docs](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).

To try the skills without personal links, put symlinks to the kit's `skills/handoff`, `skills/pickup` and `skills/lesson` directories under a throwaway workspace's `.agents/skills/`. Run Codex from that workspace with `ws` on PATH. For headless proof, use separate `codex exec --ephemeral` calls: first `$handoff <ID>` with an exact next action, then `$pickup` without supplying that action. Review hooks interactively first; `--dangerously-bypass-hook-trust` is only for automation that has already vetted every active hook. It does not replace project trust. `WS_OFFLINE=1` disables workspace network checks, not the Codex model session.

```text
ws task find <ticket>            # or MCP find_task
ws claim <ID> --worker me
… work: ws search, ws lesson search, ws digest, /thinkbeforeact …
ws checkpoint <ID> --status <s> --next "<exact next action>"
ws lesson add "what happened → rule"      # when something went wrong
ws feedback add "..." --kind friction     # when the workspace got in the way
ws release <ID>
```
