# Setup guide

Every step after 2 is optional. `ws doctor` tells you what is missing and how to install it.

## 1. Install the kit

```bash
git clone https://github.com/Alenroyfeild/ai-dev-workspace.git ~/ai-dev-workspace
echo 'export PATH="$HOME/ai-dev-workspace/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
ws --help
```

Requires Python 3.9+ and git. No pip packages.

## 2. Create a workspace

One workspace per product (it can serve several repos):

```bash
ws init ~/work/myapp-workspace --name myapp --repo ~/code/myapp --pack obsidian
cd ~/work/myapp-workspace && ws doctor
```

Keep the workspace in its own git repo (`git init`) so the memory is versioned. Put it in a private repo if it holds company knowledge.

## 3. Connect your assistant

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

Automatic: your assistant checks `ws notices` at session start and asks before updating or sharing anything. For no network at all: `export WS_OFFLINE=1`.

## Daily loop

```text
ws task find <ticket>            # or MCP find_task
ws claim <ID> --worker me
… work: ws search, ws lesson search, ws digest, /thinkbeforeact …
ws checkpoint <ID> --status <s> --next "<exact next action>"
ws lesson add "what happened → rule"      # when something went wrong
ws feedback add "..." --kind friction     # when the workspace got in the way
ws release <ID>
```
