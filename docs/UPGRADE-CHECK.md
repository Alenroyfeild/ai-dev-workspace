# Workspace upgrade check

Both checks used throwaway directories and a temporary `HOME`; no existing workspace or client config was read or changed.

The old copy came from `tests/fixtures/template-0.1.0-beta.1`. I added only synthetic user content, an unmarked Claude settings file and a schema-1 workspace record, then ran `ws upgrade --dry-run` and `ws upgrade`.

- Dry-run left every file byte-for-byte unchanged and showed 13 proposed file changes.
- Applying the upgrade staged two ambiguous user-owned files for review (`AGENTS.md` and `.claude/settings.json`) and backed up the old `workspace.json`.
- The second upgrade reported no changes.

The current copy was generated with `ws init` in another throwaway directory. Its dry-run also left every file unchanged; applying the upgrade reported zero changes, conflicts or backups.

The two proposals on the old copy were expected: the synthetic user edits were outside managed markers, so the upgrader preserved them and emitted `.ws-new` proposals instead of overwriting them.

## Record format markers

Task records carry `format: 1` in their frontmatter and new lesson metadata (`<!-- ws:lesson {...} -->`) carries `"format": 1`. The constants are `TASK_FORMAT` and `LESSON_FORMAT` in `ws/core.py`.

- A missing marker means format 1. Existing files are never rewritten just to add it.
- **Bump a format only for a change an older reader cannot default**: a renamed or removed key, or a changed meaning. Additive keys never bump it, because readers already default a missing key.
- A task with a higher format than the kit supports stays read-only. `ws brief`, `ws task find` and `ws recap` still show it (best effort) with one warning; `ws claim`, `ws checkpoint`, `ws remember` and other writes refuse with "written by a newer ai-dev-workspace (format N); update the kit". Newer lesson metadata is shown and kept as written, and the same applies to `workspace.json` with a newer `schema_version`.
- `tests/test_record_corpus.py` proves every released record corpus under `tests/fixtures/records/<version>/` still loads, and `tests/fixtures/records-future/` holds a synthetic newer-format task and lesson that prove the read-only behaviour.
