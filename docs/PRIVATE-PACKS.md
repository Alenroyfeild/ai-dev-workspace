# Local private packs

Run `ws pack add --from "/path/to/private pack"`. Use the bundled `pack.json`
contract: name, version, kind, description, optional requires/setup/selftest;
optional AGENTS.snippet.md and vault/ content. Names must differ from bundled
packs. Symlinks, special files and escaping script paths are refused.

The source's absolute path is recorded in workspace.json; keep it available.
`ws upgrade --dry-run` previews source updates; `ws upgrade` applies them with
backups. Edited files become .ws-new proposals. `ws pack remove <name>` removes
registration, unedited installed files and unedited rule blocks; edited content
is kept and reported. Setup/selftest scripts are never executed automatically.
The source is never copied into the kit or published. Keep workspace.json private
if its source paths or pack names identify your team.
