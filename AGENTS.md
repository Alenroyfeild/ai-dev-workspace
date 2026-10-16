# Working on ai-dev-workspace

- Tests: `python3 -m unittest discover -s tests` (no network, no model calls). Run the full suite before saying a change is done; name the command and the result.
- Code: standard library only in `ws/` and `mcp/`, Python 3.9+. One implementation in `ws/core.py` (or a small module next to it); the CLI and MCP server call it.
- Every invariant gets a test and every bug a regression test that fails before the fix.
- Packs and docs are public: no company, customer or personal details, paths or credentials. See CONTRIBUTING.md and docs/PACKS.md.
- Docs: short sentences, exact commands, no claim without a way to check it. User-facing changes get a CHANGELOG line under the unreleased version.
- Commit messages: a title, then `Problem:`, `Cause:` (one bullet per cause), `Fix:` and `Verified:` (only what was actually run); no Co-Authored-By trailer.
- Pull requests target `dev`. Never push to someone else's branch; never merge your own PR.
