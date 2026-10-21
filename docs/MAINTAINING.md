# Feedback, issues and releases

## The loop

Users normally never type these: the assistant reads `ws notices` (MCP `notices`) at session start and offers the next step, and offers `feedback add` when the user hits friction. The commands below are what it runs on the user's yes.


```text
user        ws feedback add "..." --kind bug|idea|friction|praise     (stays local, redacted)
user        ws feedback submit N            preview: nothing leaves the machine
user        ws feedback submit N --yes      creates a GitHub issue (gh CLI) or prints a prefilled issue URL
            ws feedback link N <url>        only needed after the URL route
maintainer  triage the issue → fix in a PR with "Fixes #N" → add a changelog.d fragment
maintainer  release (below)
user        ws doctor / ws update --check   shows the new version and its notes
user        ws update                       fast-forwards the kit clone (refuses if it has local changes)
user        ws feedback sync                ticks the local item when its issue is closed
```

Feedback is redacted before it is shown or sent, and `submit` always previews first: company names or details in feedback text should be removed by the user before `--yes`.

## Triage labels

`feedback` (all user reports) plus the kind: `bug`, `idea`, `friction`, `praise`. Add `pack:<name>` when a report is about one pack, and `good first issue` for small ones. Close an issue only by a merged fix or a reasoned "won't do" comment, so `ws feedback sync` reflects real outcomes.

## Versions

Semantic versioning in `kit.json`:
- patch `0.1.1` – fixes, docs, pack content
- minor `0.2.0` – new commands, packs or MCP tools (backward compatible)
- major `1.0.0` – breaking changes to `workspace.json`, task format or commands; ship a migration in `ws/upgrade.py` keyed on `schema_version`

## Cutting a release

After steps 1 and 2, run `bin/release-smoke` (stdlib, offline, throwaway HOME) on the final candidate: it builds the sdist and wheel, installs the wheel in a temp venv and runs version, demo, start, remember, checkpoint, brief, token redaction, doctor, recap, pr-notes, MCP and `ws start --undo` against a toy repo, then checks the artifacts for tests, `.ws` files and stray paths. Exit 0 means every required step passed. Rebuild and repeat if the candidate changes.
`--wheel PATH` tests an existing wheel, `--source` runs `bin/ws` from the checkout without building (fast, used by the tests) and `--json` prints machine-readable results.

1. Luna folds [changelog fragments](../changelog.d/README.md) at tag time in one release commit; ordinary PRs never edit `CHANGELOG.md`. First run `python3 -m unittest discover -s tests -p test_changelog_fragments.py`. Under the target `## <version> (<YYYY-MM-DD>)` heading, turn each fragment into a bullet: `Added:` goes under New, `Changed:` under Improved and `Fixed:` under Fixed. Preserve existing entries and combine duplicate bullets. Delete only the folded fragment files; keep `changelog.d/README.md`. Write a one-sentence summary first (the update notice shows it), and retain Measured and Known limits where applicable. Use absolute links in release notes; relative ones break on the release page.
2. Set the same version in `kit.json`. Save this release's record corpus under `tests/fixtures/records/<version>/` (see `docs/UPGRADE-CHECK.md`).
3. Commit the fold and version changes together. After the maintainer approves the exact candidate and its smoke results, run `git tag v<version> && git push --tags`. Do not create the GitHub Release by hand.
4. `.github/workflows/release.yml` checks the tag matches `kit.json`, runs the tests and publishes the GitHub Release as Latest with that CHANGELOG section plus upgrade steps. Users see the summary on their next `ws doctor` / `ws update --check` (checked at most once a day).
5. For PyPI, the workflow publishes GitHub release notes only. Build `dist/` from the release tag with `python3 setup.py sdist bdist_wheel`, then upload those artifacts with your PyPI publishing tool. Keep publishing credentials outside the repository.

## Repository setting

`repo` in `kit.json` is the `owner/name` that update checks and issue submission use; the `WS_REPO` environment variable overrides it. If it still starts with `OWNER/`, those commands say no GitHub repo is set.
