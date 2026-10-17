## Guards pack
A PreToolUse hook denies destructive commands (rm -rf on home or root, git reset --hard, force push, git clean -f), secrets in commands or files, and newly skipped tests. When it denies something, explain why to the user and let them decide; do not look for a way around it.
