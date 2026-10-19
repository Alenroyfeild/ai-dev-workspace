# Windows validation

The kit uses native nonblocking byte-range locks on Windows and flock on
macOS/Linux. Generated hooks pass --workspace-root to the CLI and quote paths;
they use the active Python executable on Windows. CLI/MCP streams and workspace
text use UTF-8. Relative paths in reports keep forward slashes.

From a checkout, use `python bin/ws <command>` on Windows. Optional user-level
skill links require permission to create symlinks (for example Developer Mode).
The full suite runs on windows-latest with Python 3.9 and 3.12. Client-specific
desktop flows still need live validation.

Junctions (`mklink /J`) count as links wherever ws refuses symlinks. A team folder
on a mapped or `subst` drive is accepted and stored under its real path. Worker
runs through npm `.cmd` shims (`codex.cmd`) refuse `& | < > ^ % !` in the repo
path or prompt, because cmd.exe re-parses them. Paths over 260 characters: git
runs with `core.longpaths=true` and backups use the `\\?\` form, but other tools
still need `LongPathsEnabled`.

Official APIs: [Python msvcrt.locking](https://docs.python.org/3/library/msvcrt.html),
[Microsoft _locking](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170),
[subprocess Windows argument conversion](https://docs.python.org/3/library/subprocess.html),
[taskkill /T and /F](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill).
