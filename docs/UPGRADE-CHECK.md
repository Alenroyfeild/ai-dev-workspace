# Workspace upgrade check

Both checks used throwaway directories and a temporary `HOME`; no existing workspace or client config was read or changed.

The old copy came from `tests/fixtures/template-0.1.0-beta.1`. I added only synthetic user content, an unmarked Claude settings file and a schema-1 workspace record, then ran `ws upgrade --dry-run` and `ws upgrade`.

- Dry-run left every file byte-for-byte unchanged and showed 13 proposed file changes.
- Applying the upgrade staged two ambiguous user-owned files for review (`AGENTS.md` and `.claude/settings.json`) and backed up the old `workspace.json`.
- The second upgrade reported no changes.

The current copy was generated with `ws init` in another throwaway directory. Its dry-run also left every file unchanged; applying the upgrade reported zero changes, conflicts or backups.

The two proposals on the old copy were expected: the synthetic user edits were outside managed markers, so the upgrader preserved them and emitted `.ws-new` proposals instead of overwriting them.
