# Setup guide

Every step after 2 is optional. `ws doctor` tells you what is missing and how to install it.

## 1. Install the kit

For an isolated CLI, use `pipx install git+https://github.com/Alenroyfeild/ai-dev-workspace`. This includes templates, packs, skills and the MCP server; generated client configs and hooks use the install's Python environment. `ws update` prints `pipx upgrade ai-dev-workspace` for this installation. It does not run pipx for you; `ws update --check` still checks release notes. A plain venv installation uses that venv's pip with the original source to update. The git-clone alternative follows:

```bash
git clone https://github.com/Alenroyfeild/ai-dev-workspace.git ~/ai-dev-workspace
echo 'export PATH="$HOME/ai-dev-workspace/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
ws --help
```

macOS and Linux only; Windows not supported yet (file locking uses fcntl). Requires Python 3.9+ and git. No pip packages.

## 2. Create a workspace

One workspace per product (it can serve several repos). `ws map` also links an existing `graphify-out/GRAPH_REPORT.md` and its top headings; `ws search` searches that report. The kit never runs Graphify. [Graphify PR #13](https://github.com/Alenroyfeild/ai-dev-workspace/pull/13) is pending review.

```bash
ws init ~/work/myapp-workspace --name myapp --repo ~/code/myapp --pack obsidian
cd ~/work/myapp-workspace && ws doctor
```

Keep the workspace in its own git repo (`git init`) so the memory is versioned. Put it in a private repo if it holds company knowledge.

Existing files are kept. Proposed kit content goes beside them as `.ws-new`; review and apply it manually. Existing sidecars are kept too.

## 3. Connect your assistant

Run `ws connect claude`, `ws connect cursor`, or `ws connect codex`. Project config collisions are staged as `.ws-new` and kept for review. Codex prints the exact global-config block; `ws connect codex --write` appends it with a backup, refusing conflicting entries. Init prepares Claude's config and detects the other clients. `ws doctor` reports matching configuration; approve the server in the client before using its tools.

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

Automatic: your assistant checks `ws notices` at session start and asks before updating or sharing anything. `ws tools` shows recommended, optional and caution tools; nothing installs automatically. Set `tool_profile` in `workspace.json` to `lean`, `standard` or `full`, and `tool_overrides` to per-tool `on`, `off` or `ask`. `ws tools --cost` measures MCP schemas, skill/plugin metadata and cached Codeburn use. `ws assist` asks before applying suggestions. Use `ws run import codeburn` to import local usage and update an existing entry when a session grows. Pending review: [assist #14](https://github.com/Alenroyfeild/ai-dev-workspace/pull/14), [tool cost profiles #16](https://github.com/Alenroyfeild/ai-dev-workspace/pull/16), [Codeburn import #15](https://github.com/Alenroyfeild/ai-dev-workspace/pull/15) and update #17. For no network at all: `export WS_OFFLINE=1`.

## Daily loop

Run `ws connect claude` once to link the kit skills into `~/.claude/skills`, or `ws connect codex` for `~/.agents/skills`. Existing names are kept; check the command's notice. Restart the client after connecting. With `ws` on PATH, Claude's `/handoff` saves the current task's next action, evidence and blockers, `/pickup` reads that task memory in a new session, and `/lesson` records a requested rule. In Codex, use `$handoff`, `$pickup`, and `$lesson` (or select them with `/skills`). These skills use the CLI without MCP. Init and MCP connection calls do not install global skill links.

New workspaces include Claude Code and Codex project hooks. Approve their hook definitions in the client. SessionStart injects `ws brief`; Stop requests a checkpoint once when a claim is at least 30 minutes stale. Plain `ws nudge` is read-only. Its Stop/PreCompact hooks also capture memory from Claude transcripts only, after tool use: cue-bearing user sentences and the last assistant summary/next step, redacted and capped at 150 words per dated Captured block, appended to Handoff and Evidence. Existing text and Next action stay intact; repeated identical captures are skipped. Capture requires exactly one locally owned, unfinished claim; missing/unreadable or other transcript formats are skipped. Captured text is unverified and may omit nuance; use `/handoff` for precise memory. PreCompact's reminder stays advisory; it does not inject assistant context or block compaction. Existing hook settings stay intact, with proposed settings staged as `.ws-new`.

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
