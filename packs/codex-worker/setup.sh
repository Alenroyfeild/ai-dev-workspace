#!/bin/bash
# Install the pinned Codex ACP adapter into this pack and add the read-only mode. Safe to re-run.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v npm >/dev/null || { echo "npm not found: install Node.js first"; exit 1; }
command -v acpx >/dev/null || echo "note: acpx not found; install it with: npm install -g acpx"
npm install --silent --no-audit --no-fund --prefix "$HERE/runtime" @agentclientprotocol/codex-acp@1.12.0
python3 "$HERE/patch_modes.py" "$HERE/runtime/node_modules/@agentclientprotocol/codex-acp/dist/index.js"
echo "codex-worker ready. Test it: $HERE/investigate.sh <some-dir> \"List the files here\""
