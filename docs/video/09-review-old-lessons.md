---
title: Review old lessons
duration_hint: 45s
status: Stable
ws_version: 0.1.0b7
---
## Problem
Saved lessons pile up over months, and nobody can tell which rules have gone stale without reading them all.
## Steps
```sh
ws start --yes
ws lesson add "Mocked DB hid a bad migration; run migrations in tests" --tag testing
ws lesson review
ws lesson review --days 0
ws lesson search migration
ws start --undo
```
## Guidance
Stable: `ws lesson review [--days N]` lists lessons whose date stamp is strictly older than N days (default 60) so you can review them by hand.
Real output from a fresh toy repo: the new lesson is stamped today, so `ws lesson review` prints `"days": 60`, a `"before"` date, `"undated": 0` and an empty `"lessons": []` list. `--days 0` also stays empty because only strictly older stamps are listed. `ws lesson search migration` still shows `- 2026-11-04 Mocked DB hid a bad migration; run migrations in tests #testing`.
The output states its own basis: "Lesson date stamps, not last use; review manually. Nothing is changed."
Limits:
Review is read-only: it never changes, archives or deletes a lesson; to remove one you edit the Markdown file yourself.
It reports the date a lesson was written, not when it was last useful or last used, so an old date does not mean a wrong rule.
`--days` must be a non-negative integer; a negative value is rejected with an error.
## Narration
Lessons are useful until the code they describe changes. Beta seven adds `ws lesson review`, a read-only list of lessons whose date stamp is older than sixty days, or any number you pass with `--days`. In this toy repository the only lesson was saved today, so the list is empty, and the output says plainly that nothing is changed. The review looks at the date written, not whether the lesson was ever used, so you decide by hand what is stale. It never edits or deletes a lesson.
