# Contributing

- **Feedback and bugs** – `ws feedback add "..." --kind idea|bug|friction|praise` records the text and kind locally. `ws feedback submit <n>` previews a GitHub issue with the text, kind, recorded date, kit version and enabled packs; check it for private details before `--yes`. The bug, feedback and pack-request issue forms use these same fields. See [docs/MAINTAINING.md](docs/MAINTAINING.md).
- **Public packs** – see [docs/PACKS.md](docs/PACKS.md). Keep them generic: no company or customer details. Worker packs need a self-test.
- **Private packs** – use `ws pack add --from <dir>`; the source stays local and is not copied into the public kit. Read [docs/PRIVATE-PACKS.md](docs/PRIVATE-PACKS.md), and never commit private pack content or workspace paths.
- **Benchmark scenarios** – read [bench/README.md](bench/README.md). Add scenario data under `bench/scenarios/`, with hidden checks and references outside the worker fixture. Add a test that the fixture fails the intended checks and the reference passes. Tests must never invoke a model.
- **Code** – standard library only in `ws/` and `mcp/`. One implementation in `ws/core.py`; front doors call it. Add a test for every invariant and a regression test for every bug. Run `python3 -m unittest discover -s tests`.
- **Packaging tests** – `test_pip_builds_a_wheel_from_the_sdist` and `test_sdist_and_wheel_include_pep440_metadata_and_runtime_files` in `tests/test_packaging.py` write build metadata (`build/`, `*.egg-info`) into the source checkout, so they need write access to it. A sandboxed assistant should run them with write access, or from a temporary copy of the checkout. A permission error there is an environment limit, not a packaging defect.
- **Docs** – short sentences, exact commands, no claims without a way to check them.

## Review flow

Each pull request gets a read-only Codex first-pass review with findings in `file:line: problem. fix.` form. Claude verifies those findings and runs any required client or integration proof; the maintainer decides whether to merge. Codex reviewers do not push, approve or merge.
