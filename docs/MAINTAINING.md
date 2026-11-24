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
   - First run `python3 -m unittest discover -s tests -p test_changelog_fragments.py`.
   - Fold [changelog fragments](../changelog.d/README.md) into `CHANGELOG.md` under `## <version> (Unreleased)`. Turn each fragment into a bullet: `Added:` goes under New, `Changed:` under Improved and `Fixed:` under Fixed. Allowed subsections are `New`, `Improved`, `Fixed`, `Previews`, `Known limits`, and `Measured`. Preserve existing entries and combine duplicate bullets. Write a one-sentence summary first (the update notice shows it), and retain Measured and Known limits where applicable. Use absolute links in release notes; relative ones break on the release page. Delete the folded fragment files; keep `changelog.d/README.md`.
   - Bump version in `kit.json`, `server.json` (2 fields), the five plugin manifests (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, `.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json`), and `tests/test_packaging.py`.
   - Save this release's record corpus under `tests/fixtures/records/v<version>/` (see `docs/UPGRADE-CHECK.md`).
   - Add a video script per `### New` feature under `docs/video/`; make README and `llms.txt`/`llms-full.txt` name each new feature (a `## Released in beta.N` section, or `## Released in X.Y.Z` for a final release, and every backticked `ws` command from New in README), enforced by `tests/test_release_sync.py`.
   - Update documentation: add new capabilities to `docs/ROADMAP.md` under "Available in the beta", update `docs/CLIENT-VERIFICATION.md` to `## beta.N release coverage` (`## X.Y.Z release coverage` for a final release), and update preview labels in `docs/SETUP.md` and `docs/DISCOVERY.md` to `Preview in beta.N` (`Preview in X.Y.Z`). For a final version only the last beta's labels (the highest `## X.Y.Z-beta.N` heading in `CHANGELOG.md`) stay valid as the previous release; older or newer beta labels are errors.
   - Run the full test suite in a temp HOME and `bin/release-smoke` on the built wheel. Open the RC PR to `dev` and merge once peer-reviewed and CI is green.

2. **Dating PR to `dev`:**
   - Freeze `dev`.
   - Open a PR that replaces `## <version> (Unreleased)` with `## <version> (<YYYY-MM-DD>)` in `CHANGELOG.md` and moves the published-version text (next bullet).
   - In the same PR, move all published-version text to the new version: README `v<version> on PyPI`, `llms.txt` and `llms-full.txt` `published <canonical-version>`, the `docs/DISCOVERY.md` PyPI link and `PUBLISHED_VERSION` in `tests/test_published_docs.py`. The tagged tree is what PyPI and GitHub show, so this cannot wait until after the upload.
   - Verify `changelog.d/` contains only `README.md`.
   - Merge to `dev` after review and green CI.

3. **`dev` → `main` promotion PR:**
   - Open a PR from `dev` to `main`.
   - The diff against `main` should reflect only the tested release commits.
   - Run TAG-CHECK verification: confirm byte-equal wheel members against candidate and verify `bin/release-smoke` passes.
   - On the exact promotion PR head, run `WS_RELEASE_CHECK=1 python3 -m unittest discover -s tests -p test_release_sync.py`. Require it to pass before the tag, and rerun it if the head changes.
   - Maintainer reviews and merges `dev` → `main`.

4. **Tag on the `main` merge commit:**
   - The annotated tag `v<version>` is placed on the merge commit on `main` (never directly on `dev`).
   - The maintainer tags and pushes: `git tag -a v<version> -m "v<version>" <main-merge-sha> && git push origin v<version>`. Do not create the GitHub Release by hand.

5. **Automated GitHub Release (with fallback):**
   - `.github/workflows/release.yml` checks that the tag matches `kit.json`, runs the tests, and creates a draft GitHub Release with that CHANGELOG section plus upgrade steps. The draft is not visible to update checks.
   - Within 10 minutes of pushing the tag, `gh run list --workflow release.yml --limit 1` must show a run for the tag; if not, use the fallback. Then `gh release view v<version> --json isDraft` must show `true`.
   - *Fallback:* If `release.yml` does not start (e.g. GitHub Actions outage), run `bin/publish-release v<version> notes.md` with notes built by `release.yml`'s own awk and printf commands; the script is idempotent with a late workflow run.

6. **PyPI publication:**
   - One-time maintainer setup: in PyPI, register a trusted publisher for project `ai-dev-workspace` with owner `Alenroyfeild`, repository `ai-dev-workspace`, workflow filename `pypi-publish.yml`, and environment `pypi`. In the GitHub repository create the `pypi` environment with a required reviewer. Complete both before using the workflow. The workflow must be present on the default branch; a draft PR alone cannot publish.
   - After the maintainer creates the tag in step 4 and approves publication, run `gh workflow run pypi-publish.yml --ref main -f tag=v<version>`. The workflow refuses a tag whose commit is not reachable from `origin/main`, validates the tagged archive's `kit.json` and dated CHANGELOG heading, builds in an unprivileged job, and asks the `pypi` environment reviewer before the OIDC upload job. The workflow takes no upload credential.
   - Download the run's `pypi-dist` artifact, for example `gh run download <run-id> -n pypi-dist -D <dist-dir>`. Compare the sha256 values in the PyPI JSON (`https://pypi.org/pypi/ai-dev-workspace/<canonical-version>/json`) with `shasum -a 256 <dist-dir>/*`. The artifact files are exactly those uploaded by the workflow.
   - Manual build fallback and independent comparison: on Ubuntu 24.04 with Python 3.12.8, create a clean release venv with `build==1.2.2.post1`, `setuptools==75.8.2`, `wheel==0.45.1` and Twine. Extract `git archive v<version> | tar -x -C <tmp>`, set `SOURCE_DATE_EPOCH` to `git show -s --format=%ct v<version>^{commit}`, run `python -m build --no-isolation` from `<tmp>`, then run `<checkout>/bin/normalize-sdist <tmp>/dist/*.tar.gz "$SOURCE_DATE_EPOCH"` and `twine check <tmp>/dist/*`. The normalization makes the source archive's metadata repeatable; use the same pinned tools and platform for an independent hash comparison. **Emergency-only fallback**, second to the workflow: if OIDC or Actions is unavailable, the maintainer may create a project-scoped token for this upload. Run `env -u TWINE_PASSWORD -u TWINE_NON_INTERACTIVE -u TWINE_REPOSITORY -u TWINE_REPOSITORY_URL PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring twine upload --repository-url https://upload.pypi.org/legacy/ --config-file /dev/null --username __token__ <tmp>/dist/*`. The token must be typed into the terminal at the password prompt, never stored in a file, keyring, environment variable, shell history or workflow. Revoke the project-scoped token immediately after the upload attempt. Compare hashes as above.
   - Only after the PyPI hashes match, the maintainer publishes the GitHub Release: `gh release edit v<version> --draft=false --prerelease=false --latest`. Check `gh release view v<version>` shows Latest, not draft. Update checks can now point to the published version.

7. **MCP registry publication:**
   - `server.json` already carries the version (step 1). Run `mcp-publisher login github`, `mcp-publisher validate`, then `mcp-publisher publish` (name `io.github.Alenroyfeild/ai-dev-workspace`).
   - Verify: `curl -s "https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Alenroyfeild%2Fai-dev-workspace/versions/latest"` shows the new version.
   - The namespace is case-sensitive and each version can be published only once; a 400 duplicate-version means it is already published.

8. **Release-surface verification:**
   - Run `bin/release-verify <canonical-version>` (`0.1.0b7` for a beta, `0.2.0` for a final release) after publication surfaces have been updated. This read-only check compares the latest PyPI release, latest non-draft GitHub Release, latest MCP Registry version, all package/plugin manifests on `main`, and README/LLMS version text on `main`.
   - A stale surface exits nonzero and prints one line naming each mismatch. Plugin `Live-checked on beta.N` (or `X.Y.Z`) labels are informational; do not change them without a live plugin check.
   - The video release check is included. Run this step again after step 9 if videos were not ready yet.

9. **Videos after PyPI:**
   - Owner: maintainer. Complete this post-tag follow-up within 3 days of the tag.
   - Record and upload a short per `### New` feature (scripts in `docs/video/`, written in the RC PR), add the edition to `docs/video/videos.json`, then run `bin/make-video --links`.
   - `bin/make-video --release-check <canonical-version>` must exit 0.

10. **Plugin live check:**
   - Owner: maintainer. Complete this post-tag follow-up within 3 days of the tag.
   - Live-install the Claude Code plugin from the marketplace on the released version, then update the `Live-checked on beta.N (date)` (or `X.Y.Z (date)`) labels (README, `llms.txt`, `llms-full.txt`, `docs/CLIENT-VERIFICATION.md`). If this was not done, leave the labels as they are.

11. **If PyPI failed or was delayed:** revert the published-version lines moved in step 2 (README, `llms.txt`, `llms-full.txt`, `docs/DISCOVERY.md`, `PUBLISHED_VERSION`) until the upload succeeds.

**Landing:** merge a PR only at 7/7 checks, with `gh pr merge <n> --merge --match-head-commit <reviewed sha>`. Land one PR at a time and wait for each post-merge CI before the next.

Run `bin/release-smoke` (stdlib, offline, throwaway HOME) on the final candidate before merging: it builds the sdist and wheel, installs the wheel in a temp venv and runs version, demo, start, remember, checkpoint, brief, token redaction, doctor, recap, pr-notes, MCP and `ws start --undo` against a toy repo, then checks the artifacts for tests, `.ws` files and stray paths. Exit 0 means every required step passed. Rebuild and repeat if the candidate changes.
`--wheel PATH` tests an existing wheel, `--source` runs `bin/ws` from the checkout without building (fast, used by the tests) and `--json` prints machine-readable results.

### Files each release touches

| File | What changes | When | Enforcing test |
| --- | --- | --- | --- |
| `kit.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `.codex-plugin/plugin.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `.cursor-plugin/plugin.json`, `.cursor-plugin/marketplace.json` | Version string bump | RC PR | `tests/test_packaging.py` |
| `server.json` | Version strings (2 fields) | RC PR | `tests/test_packaging.py` |
| `tests/test_packaging.py` | Version string assertion | RC PR | `tests/test_packaging.py` |
| `CHANGELOG.md` | Fold fragments into New/Improved/Fixed/Previews/Known limits/Measured, write summary | RC PR | `tests/test_release_sync.py` |
| `CHANGELOG.md` | Date `(YYYY-MM-DD)` replaces `(Unreleased)` | Dating PR | `tests/test_release_sync.py` |
| `changelog.d/*` | Fragment files deleted, keeping only `README.md` | RC PR / Dating PR | `tests/test_release_sync.py` |
| `tests/fixtures/records/v<version>/` | Record corpus generated for release version | RC PR | `tests/test_release_sync.py`, `tests/test_record_corpus.py` |
| `docs/ROADMAP.md` | New features added under "Available in the beta" | RC PR | `tests/test_release_sync.py` |
| `docs/CLIENT-VERIFICATION.md` | Release coverage heading updated to `beta.N release coverage` (`X.Y.Z release coverage` for a final release) | RC PR | `tests/test_release_sync.py` |
| `docs/SETUP.md`, `docs/DISCOVERY.md` | Preview labels updated to `Preview in beta.N` (`Preview in X.Y.Z`) | RC PR | `tests/test_release_sync.py` |
| `README.md` | Update PyPI version string `v<version> on PyPI`; name each new `ws` command and feature | Dating PR (features: RC PR) | `tests/test_published_docs.py`, `tests/test_release_sync.py` |
| `llms.txt`, `llms-full.txt` | Update `published <canonical-version>`; add `## Released in beta.N` (`## Released in X.Y.Z` for a final release) | Dating PR (section: RC PR) | `tests/test_published_docs.py`, `tests/test_release_sync.py` |
| `docs/DISCOVERY.md` | Update PyPI link to release version | Dating PR | `tests/test_published_docs.py` |
| `tests/test_published_docs.py` | Bump `PUBLISHED_VERSION` constant | Dating PR | `tests/test_release_sync.py` (release mode) |
| `server.json` | Publish to MCP registry (`io.github.Alenroyfeild/ai-dev-workspace`) | After PyPI publish (step 7) | `tests/test_packaging.py` |
| `docs/video/videos.json` | Add the release edition after recording | After PyPI publish (step 9) | `tests/test_make_video.py`, `bin/make-video --release-check` |
| README, `llms.txt`, `llms-full.txt`, `docs/CLIENT-VERIFICATION.md` | `Live-checked on beta.N (date)` (`X.Y.Z (date)`) labels | After plugin live check (step 10) | none; leave unchanged if not checked |

## Repository setting

`repo` in `kit.json` is the `owner/name` that update checks and issue submission use; the `WS_REPO` environment variable overrides it. If it still starts with `OWNER/`, those commands say no GitHub repo is set.
