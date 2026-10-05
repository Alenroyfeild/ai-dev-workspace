#!/bin/bash
# Read-only Codex worker. Usage: investigate.sh <dir> "<prompt>"
# WS_CODEX_TIER=worker (newest *-luna, high) | planner (newest *-sol, low). Override families with WS_CODEX_WORKER/WS_CODEX_PLANNER.
set -euo pipefail
DIR="$(cd "$1" && pwd)"; PROMPT="$2"; S="wsi-$$"; HERE="$(cd "$(dirname "$0")" && pwd)"
A="node $HERE/runtime/node_modules/@agentclientprotocol/codex-acp/dist/index.js"
[ -f "$HERE/runtime/node_modules/@agentclientprotocol/codex-acp/dist/index.js" ] || { echo "Run $HERE/setup.sh first"; exit 1; }
if [ "${WS_CODEX_TIER:-worker}" = planner ]; then FAMILY="${WS_CODEX_PLANNER:-sol}"; EFFORT=low; else FAMILY="${WS_CODEX_WORKER:-luna}"; EFFORT=high; fi
trap 'acpx --agent "$A" --cwd "$DIR" sessions close "$S" >/dev/null 2>&1 || true' EXIT
acpx --agent "$A" --cwd "$DIR" sessions new -s "$S" >/dev/null
acpx --agent "$A" --cwd "$DIR" set-mode ws-investigator -s "$S" >/dev/null
# An unknown model id makes the adapter list live models; pick the newest in the family.
LIST="$( (acpx --agent "$A" --cwd "$DIR" set model __list__ -s "$S" 2>&1 || true) | sed -n 's/.*Available models: //p')"
MODEL="$(python3 -c "import re,sys;m=[x.strip(' .') for x in sys.argv[1].split(',') if x.strip(' .').endswith('-'+sys.argv[2])];v=lambda x:[int(n) for n in re.findall(r'\d+',x)];print(max(m,key=v) if m else '')" "$LIST" "$FAMILY")"
[ -n "$MODEL" ] && acpx --agent "$A" --cwd "$DIR" set model "$MODEL" -s "$S" >/dev/null
# Some Codex builds reject effort changes; keep going on the default and say so.
acpx --agent "$A" --cwd "$DIR" set reasoning_effort "$EFFORT" -s "$S" >/dev/null 2>&1 || EFFORT="default (adapter refused $EFFORT)"
echo "[codex-worker] model=${MODEL:-default} effort=$EFFORT mode=ws-investigator (read-only)" >&2
acpx --agent "$A" --timeout "${WS_CODEX_TIMEOUT:-600}" --cwd "$DIR" prompt -s "$S" "$PROMPT"
