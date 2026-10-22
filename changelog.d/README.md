# Changelog fragments

Each PR adds `changelog.d/<branch-name-with-slashes-as-dashes>.md` instead of editing
`CHANGELOG.md`. For example, branch `codex/fix-brief` uses `codex-fix-brief.md`.

Write UTF-8 text with exactly one line: `Fixed:`, `Added:` or `Changed:`, then one
space and the user-visible change. Do not start with a Markdown bullet or add blank
lines. Backticks and links are fine. For example:

```text
Fixed: `ws brief` keeps the current task's saved decisions.
```

Check fragments with:

```sh
python3 -m unittest discover -s tests -p test_changelog_fragments.py
```

Luna folds them into the release changelog at tag time, as described in
[Maintaining](../docs/MAINTAINING.md#cutting-a-release). Keep this README when deleting
folded fragments. Tags and releases still require the maintainer's approval.
