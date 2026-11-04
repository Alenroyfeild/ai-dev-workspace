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

The release workflow uses two promotion steps and tags the merge commit on `main`, keeping `dev` as the integration branch:

1. **Release Candidate (RC) PR to `dev`:**
   - Fold [changelog fragments](../changelog.d/README.md) into `CHANGELOG.md` under `## <version> (Unreleased)`. Turn each fragment into a bullet: `Added:` goes under New, `Changed:` under Improved and `Fixed:` under Fixed. Allowed subsections are `New`, `Improved`, `Fixed`, `Previews`, `Known limits`, and `Measured`. Delete the folded fragment files; keep `changelog.d/README.md`. Write a one-sentence summary at the top of the section.
   - Bump version in `kit.json`, `server.json` (2 fields), the plugin manifests (`.codex-plugin`, `.cursor-plugin`, `.claude-plugin`), and `tests/test_packaging.py`.
   - Save this release's record corpus under `tests/fixtures/records/v<version>/` (see `docs/UPGRADE-CHECK.md`).
   - Update documentation: add new capabilities to `docs/ROADMAP.md` under "Available in the beta", update `docs/CLIENT-VERIFICATION.md` to `## beta.N release coverage`, and update preview labels in `docs/SETUP.md` and `docs/DISCOVERY.md` to `Preview in beta.N`.
   - Run the full test suite in a temp HOME and `bin/release-smoke` on the built wheel. Open the RC PR to `dev` and merge once peer-reviewed and CI is green.

2. **One-line dating PR to `dev`:**
   - Freeze `dev`.
   - Open a one-line PR replacing `## <version> (Unreleased)` with `## <version> (<YYYY-MM-DD>)` in `CHANGELOG.md`.
   - Verify `changelog.d/` contains only `README.md`.
   - Merge to `dev` after review and green CI.

3. **`dev` → `main` promotion PR:**
   - Open a PR from `dev` to `main`.
   - The diff against `main` should reflect only the tested release commits.
   - Run TAG-CHECK verification: confirm byte-equal wheel members against candidate and verify `bin/release-smoke` passes.
   - Maintainer reviews and merges `dev` → `main`.

4. **Tag on the `main` merge commit:**
   - The tag `v<version>` is placed on the merge commit on `main` (never directly on `dev`).
   - The maintainer tags and pushes: `git tag v<version> <main-merge-sha> && git push origin v<version>`. Do not create the GitHub Release by hand.

5. **Automated GitHub Release:**
   - `.github/workflows/release.yml` checks that the tag matches `kit.json`, runs the tests, and publishes the GitHub Release as Latest with that CHANGELOG section plus upgrade steps. Users see the summary on their next `ws doctor` / `ws update --check`.

6. **PyPI publication:**
   - Checkout the release tag on `main`.
   - Build distribution packages using `python3 -m build` (or `python3 -m build --no-isolation`).
   - Upload `dist/*` artifacts using PyPI publishing tools. Keep publishing credentials outside the repository.

7. **Post-PyPI documentation PR to `dev`:**
   - After the release appears on PyPI, open a documentation PR to `dev`:
     - Update `README.md` to `v<version> on PyPI`.
     - Update `llms.txt` and `llms-full.txt` to `published <canonical-version>`.
     - Update `docs/DISCOVERY.md` with the new PyPI URL.
     - Bump `PUBLISHED_VERSION` in `tests/test_published_docs.py`.

Run `bin/release-smoke` (stdlib, offline, throwaway HOME) on the final candidate before merging: it builds the sdist and wheel, installs the wheel in a temp venv and runs version, demo, start, remember, checkpoint, brief, token redaction, doctor, recap, pr-notes, MCP and `ws start --undo` against a toy repo, then checks the artifacts for tests, `.ws` files and stray paths. Exit 0 means every required step passed. Rebuild and repeat if the candidate changes.
`--wheel PATH` tests an existing wheel, `--source` runs `bin/ws` from the checkout without building (fast, used by the tests) and `--json` prints machine-readable results.

### Files each release touches

| File | What changes | When | Enforcing test |
| --- | --- | --- | --- |
| `kit.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `.codex-plugin/plugin.json`, `.codex-plugin/marketplace.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `server.json` | Version strings (2 fields) | RC PR | `tests/test_packaging.py` |
| `tests/test_packaging.py` | Version string assertion | RC PR | `tests/test_packaging.py` |
| `CHANGELOG.md` | Fold fragments into New/Improved/Fixed/Previews/Known limits/Measured, write summary | RC PR | `tests/test_release_sync.py` |
| `CHANGELOG.md` | Date `(YYYY-MM-DD)` replaces `(Unreleased)` | Dating PR | `tests/test_release_sync.py` |
| `changelog.d/*` | Fragment files deleted, keeping only `README.md` | RC PR / Dating PR | `tests/test_release_sync.py` |
| `tests/fixtures/records/v<version>/` | Record corpus generated for release version | RC PR | `tests/test_release_sync.py`, `tests/test_record_corpus.py` |
| `docs/ROADMAP.md` | New features added under "Available in the beta" | RC PR | `tests/test_release_sync.py` |
| `docs/CLIENT-VERIFICATION.md` | Release coverage heading updated to `beta.N release coverage` | RC PR | `tests/test_release_sync.py` |
| `docs/SETUP.md`, `docs/DISCOVERY.md` | Preview labels updated to `Preview in beta.N` | RC PR | `tests/test_release_sync.py` |
| `README.md` | Update PyPI version string `v<version> on PyPI` | After PyPI publish | `tests/test_published_docs.py` |
| `llms.txt`, `llms-full.txt` | Update `published <canonical-version>` | After PyPI publish | `tests/test_published_docs.py` |
| `docs/DISCOVERY.md` | Update PyPI link to release version | After PyPI publish | `tests/test_published_docs.py` |
| `tests/test_published_docs.py` | Bump `PUBLISHED_VERSION` constant | After PyPI publish | `tests/test_published_docs.py` |
| `docs/video/videos.json` | Update when new video assets are recorded | When new videos ship | `tests/test_record_corpus.py` |

## Repository setting

`repo` in `kit.json` is the `owner/name` that update checks and issue submission use; the `WS_REPO` environment variable overrides it. If it still starts with `OWNER/`, those commands say no GitHub repo is set.
