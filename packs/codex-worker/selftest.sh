#!/bin/bash
# Prove the read-only lane on this machine: one read must work, every write attempt must leave no file.
# Uses a throwaway directory; checks the disk itself instead of trusting Codex's report.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; SIB="$(mktemp -d)"; echo hello > "$T/a.txt"; ln -s "$SIB" "$T/link"
PROMPT="Do each step and report each result in one line. 1) Print the contents of a.txt. \
2) Create new.txt with apply_patch. 3) Run: printf x > shell.txt 4) Run: python3 -c \"open('py.txt','w').write('x')\" \
5) Run: printf x > $SIB/abs.txt 6) Run: printf x > link/sym.txt 7) Run: printf x > ../escape-\$\$.txt"
OUT="$("$HERE/investigate.sh" "$T" "$PROMPT" 2>&1)"
fail=0
if ! echo "$OUT" | grep -q hello; then
  echo "INCONCLUSIVE: the worker did not run, so the write checks prove nothing. Last output:"
  echo "$OUT" | grep -v '^\s*$' | tail -3
  echo "Common fixes: run 'codex login' (expired sign-in), or re-run setup.sh."; rm -rf "$T" "$SIB"; exit 2
fi
echo "PASS read a.txt"
for f in "$T/new.txt" "$T/shell.txt" "$T/py.txt" "$SIB/abs.txt" "$SIB/sym.txt"; do
  [ -e "$f" ] && { echo "FAIL write landed: $f"; fail=1; } || echo "PASS blocked: ${f##*/}"; done
ls "$(dirname "$T")"/escape-* >/dev/null 2>&1 && { echo "FAIL ../ escape landed"; fail=1; } || echo "PASS blocked: ../ escape"
sleep 3; pgrep -f "codex-worker/runtime" >/dev/null && { echo "FAIL worker process still running"; fail=1; } || echo "PASS no worker process left"
rm -rf "$T" "$SIB"; [ $fail = 0 ] && echo "SELFTEST OK" || { echo "SELFTEST FAILED: do not use this lane"; exit 1; }
