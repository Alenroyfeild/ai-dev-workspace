# Windows validation

The branch uses native nonblocking byte-range locks on Windows and flock on
macOS/Linux. Generated hooks pass --workspace-root to the CLI and quote paths;
they use the active Python executable on Windows. CLI/MCP streams and workspace
text use UTF-8. Relative paths in reports keep forward slashes.

From a checkout, use `python bin/ws <command>` on Windows. Optional user-level
skill links require permission to create symlinks (for example Developer Mode).
The full suite runs on windows-latest with Python 3.9 and 3.12; client-specific
desktop UI flows still need their own live validation. Both versions passed all 108 tests in [native CI](https://github.com/Alenroyfeild/ai-dev-workspace/actions/runs/37677152766).

Official APIs: [Python msvcrt.locking](https://docs.python.org/3/library/msvcrt.html),
[Microsoft _locking](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170),
[subprocess Windows argument conversion](https://docs.python.org/3/library/subprocess.html),
[taskkill /T and /F](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill).
