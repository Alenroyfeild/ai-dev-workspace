# Writing a pack

A pack is a folder in `packs/<name>/`. Only `pack.json` is required.

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

- `kind`: `domain` (knowledge for a platform), `worker` (a cheaper executor), or `editor` (a way to read the vault).
- `requires`: each entry has `cmd` (checked on PATH) or `app` (checked in /Applications), plus `why` and `install`. `ws doctor` shows unmet ones with the install line.

## Rules for good packs

- Generic knowledge only. No company names, URLs, credentials or customer data: packs are public.
- Runbooks are procedures someone can follow without the author. Cite commands exactly.
- A worker pack that can change files or run commands must ship a `selftest.sh` that checks effects on disk and prints `SELFTEST OK` only when every check passed.
- Use `<kit>` in `AGENTS.snippet.md` for paths into the kit; `ws` replaces it with the real path.
- Add a test in `tests/` if the pack adds code.
