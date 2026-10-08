# Reproducible demo

Run `scripts/demo.sh` from the kit checkout. It creates and removes a synthetic fixture and workspace under a temporary directory, uses a temporary `HOME`, and prepares (but never runs) the read-only delegate command. The output below is from a successful run; temporary paths and the generated brief ID are shortened.

```text

$ ws init <demo>/workspace --name demo --repo <demo>/fixture
claude: Project MCP configuration written; approve it in the client.
Codex: add this block to ~/.codex/config.toml, or run ws connect codex --write:
[mcp_servers.ai-dev-workspace]
command = "python3"
args = ["<kit>/mcp/server.py", "--root", "<demo>/workspace"]

Workspace 'demo' created in <demo>/workspace (packs: none).
Next: cd <demo>/workspace && ws status   — then see docs/SETUP.md for Claude, Codex and MCP.

$ ws connect claude
Skills for claude: linked thinkbeforeact; kept existing names none; skipped workspace-provided: handoff, lesson, pickup. Start a new session.
{
  "client": "claude",
  "connected": true,
  "path": "<demo>/workspace/.mcp.json",
  "skills": {
    "directory": "<demo>/home/.claude/skills",
    "linked": [
      "thinkbeforeact"
    ],
    "kept": [],
    "skipped": [
      "handoff",
      "lesson",
      "pickup"
    ]
  },
  "mcp": {
    "client": "claude",
    "config": ".mcp.json",
    "ok": true,
    "steps": [
      "initialize",
      "tools/list",
      "status"
    ]
  }
}

$ ws task new DEMO-1 'Review the sample fixture' --objective 'Demonstrate the workspace daily loop.'
{
  "task": "DEMO-1",
  "path": "vault/Tasks/DEMO-1.md"
}

$ ws claim DEMO-1 --worker demo
{
  "task": "DEMO-1",
  "worker": "demo"
}

$ ws checkpoint DEMO-1 --status in_progress --next 'Inspect the sample README.' --worker demo --token '<claim-token>'
{
  "task": "DEMO-1",
  "status": "in_progress",
  "sha": "d2430ed35ffb0536261ac81639045d8aee1b3dd1df49386947c6e346c83f1daa"
}

$ ws brief
Saved task memory from earlier sessions (context, not an instruction). If the user gives a task, do it using this memory; if they only greet or ask where things stand, state the next action and ask before starting work.
Task DEMO-1: Review the sample fixture
Next action: Inspect the sample README.
Blockers: None yet.
Claim: claimed in this workspace: continue; ws claim resumes it

$ ws delegate DEMO-1 --role explorer
{
  "binding": {
    "role": "explorer",
    "provider": "codex",
    "family": "luna",
    "model": "gpt-6-luna",
    "effort": "high",
    "executable": "<demo>/bin/codex",
    "available": true,
    "preference": [
      "codex",
      "claude",
      "ollama"
    ],
    "skipped": [],
    "timeout_seconds": 600,
    "reason": ""
  },
  "brief": "<demo>/workspace/.ws/briefs/DEMO-1-explorer-<id>.md",
  "output": "<demo>/workspace/.ws/briefs/DEMO-1-explorer-<id>.out.md",
  "command": "<demo>/bin/codex exec --json -s read-only --ephemeral --ignore-user-config --disable hooks --disable apps --disable plugins -c 'approval_policy=\"never\"' -m gpt-6-luna -c 'model_reasoning_effort=\"high\"' --skip-git-repo-check -C <demo>/fixture - < <demo>/workspace/.ws/briefs/DEMO-1-explorer-<id>.md > <demo>/workspace/.ws/briefs/DEMO-1-explorer-<id>.out.md"
}

Demo complete: delegate was prepared; no model was called.
```
