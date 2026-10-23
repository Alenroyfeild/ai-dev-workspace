# Video lessons

## Rendering

Before recording, the maintainer supplies an isolated released-package venv:
`python3 -m venv /tmp/video-venv`, then
`/tmp/video-venv/bin/python -m pip install ai-dev-workspace==0.1.0b5`.
The renderer never installs anything. Use `--ws-python /tmp/video-venv/bin/python`:

```sh
python3 bin/make-video --check
python3 bin/make-video --ws-python /tmp/video-venv/bin/python
```

Clips are not rendered yet: the VHS browser failed to start in the sandbox.
The maintainer renders locally after landing; encoding and visual layout remain unverified.

## Publishing videos (every release)
Rules:
- Each release has one edition in `docs/video/videos.json`, keyed by the package version (`"latest"` names the newest). It holds an explainer, an under-the-hood tour and feature shorts.
- Only YouTube links (`https://www.youtube.com/watch?v=…` or `https://youtu.be/…`) or `null` are allowed. Nothing is linked before it is uploaded, so the README never shows a dead link.
- Videos follow the same claim rules as the docs: illustrations are labelled, terminal text is real output, each feature carries its limit, and unreleased features are marked "Coming in" their release.

Steps:
1. Re-render after the release is tagged, so the videos match the published package.
2. Upload (maintainer), then paste the URLs into a new `videos.json` entry for the version and set `"latest"`.
3. Run `bin/make-video --links`. It rewrites the `<!-- videos:start -->` blocks in README.md and docs/TUTORIAL.md (a test fails if they drift).
4. Run `bin/make-video --release-check <version>`. It exits 1 and lists what is missing until the edition, the explainer and the README links are all in place.
5. Earlier editions stay in `videos.json` and appear under "Earlier editions".
