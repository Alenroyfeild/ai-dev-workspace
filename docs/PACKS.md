# Writing a pack

A pack is a folder in `packs/<name>/`. Only `pack.json` is required.

`codex-worker` is legacy; it remains for existing ACP users. The supported worker path is `ws delegate`, whose hostile selftest passed Codex on macOS on 2026-10-07: positive token read, patch/shell/Python/absolute/symlink/parent-path writes and a Git commit attempt, with unchanged disk state. Run `ws delegate --selftest --provider codex` after CLI or sandbox changes; this proof does not establish every platform or future version. Claude execution has not been verified.

```text
packs/android/
  pack.json             manifest (required)
  AGENTS.snippet.md     rules appended to the workspace AGENTS.md (keep it under ~100 words: it loads every session)
  vault/                files merged into the workspace vault (runbooks, product templates…)
  setup.sh              optional one-time install, run by the user
  selftest.sh           optional proof that the pack works on this machine
```

## pack.json

```json
{
  "name": "android",
  "version": "0.1.0",
  "kind": "domain",
  "description": "One sentence: what the pack adds.",
  "requires": [
    {"cmd": "adb", "why": "device logs", "install": "brew install android-platform-tools", "optional": true}
  ],
  "setup": "setup.sh",
  "selftest": "selftest.sh"
}
```

- `kind`: `domain` (knowledge for a platform), `worker` (a cheaper executor), `editor` (a way to read the vault), `rules` (opt-in guidelines like `behavior`, coming in beta.6), or `guard` (the built-in `guards` and `discipline` packs: hooks that `ws start` adds to Claude Code and Codex while the pack is on).
- `next`: optional lines `ws pack add` prints after installing, such as "run ws start again".
- `requires`: each entry has `cmd` (checked on PATH) or `app` (checked in /Applications), plus `why` and `install`. `ws doctor` shows unmet ones with the install line.

## Rules for good packs

- Generic knowledge only. No company names, URLs, credentials or customer data: packs are public.
- Runbooks are procedures someone can follow without the author. Cite commands exactly.
- A worker pack that can change files or run commands must ship a `selftest.sh` that checks effects on disk and prints `SELFTEST OK` only when every check passed.
- Use `<kit>` in `AGENTS.snippet.md` for paths into the kit; `ws` replaces it with the real path.
- Add a test in `tests/` if the pack adds code.

## Optional digest advice

Coming in beta.6: In a started repo, run `ws pack add digest`, then `ws start` to review and apply
local hook changes. Restart Claude Code or Codex to refresh its MCP catalog.
The core profile then lists `digest_file` alongside the seven memory tools;
explicit custom tool lists stay unchanged. The existing tool accepts `path` and
optional `focus`, reads only workspace/linked-repo files, and redacts summaries.

For successful tool outputs above 40 KB (40,000 bytes), a PostToolUse hook adds a size-only
suggestion to use `ws digest <file>` or `digest_file`. Structured responses are
measured as compact UTF-8 JSON. The hook never saves the output, changes it,
blocks a call or creates a summary automatically. Save a log inside an allowed
repo yourself before digesting it. Smaller, malformed or unrelated events are
ignored. The hint is advisory and contains no tool-output text or input paths.

Remove it with `ws pack remove digest`, rerun `ws start`, and restart the client.
This removes the advertised extra tool and hook. Existing digest calls remain
available by name, as with other tools outside the selected MCP profile.

[Headroom](https://github.com/headroomlabs-ai/headroom/tree/e995eb9f1dacac7ed548758406de6c1508caef95)
(Apache-2.0) inspired the large-output reminder; no code or prose was copied.
Headroom is a separate compression proxy/adapter, chosen and configured by the
user. This pack adds no proxy, routes no traffic, requires no dependency and
makes no claim about combined live compatibility or savings.

Contracts: [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools),
[Claude hooks](https://code.claude.com/docs/en/hooks) and
[Codex hooks](https://developers.openai.com/codex/hooks/). The hook returns only
`hookSpecificOutput.additionalContext`; clients decide how to present it.
