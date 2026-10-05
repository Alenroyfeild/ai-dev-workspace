#!/usr/bin/env python3
"""Add ws-investigator (real readOnly sandbox, approvals never) to codex-acp@1.12.0.

Stock 1.12.0 maps its "read-only" mode to a workspace-write sandbox (upstream PR
agentclientprotocol/codex-acp#487). Verified by sha256 so a different build is never patched blindly.
"""
import hashlib, sys
from pathlib import Path

UPSTREAM_SHA = 'f45a64dc3a994556ebdb688dc8d59b86945a9b2f940a3e3e545739dd265a7cc5'
ANCHOR = '  static DEFAULT_AGENT_MODE = _AgentMode.Agent;'
ALL_OLD = '    return [_AgentMode.ReadOnly, _AgentMode.Agent, _AgentMode.AgentFullAccess];'
MODE = '''  // ai-dev-workspace: real read-only sandbox, approvals never (no self-approved escapes).
  static WsInvestigator = new _AgentMode("ws-investigator", "Investigator (read-only)",
    "Read files only; no approval can grant a write.", "standard", "never", "user",
    { type: "readOnly", networkAccess: false }, "read-only");
'''

def main(path):
    p = Path(path); s = p.read_text()
    if 'ws-investigator' in s:
        print('already patched'); return
    if hashlib.sha256(s.encode()).hexdigest() != UPSTREAM_SHA:
        sys.exit('codex-acp build differs from the verified 1.12.0; not patching. Re-run the hostile tests before trusting another build.')
    if s.count(ANCHOR) != 1 or s.count(ALL_OLD) != 1:
        sys.exit('patch anchors not found')
    s = s.replace(ANCHOR, MODE + ANCHOR).replace(ALL_OLD, ALL_OLD.replace('];', ', _AgentMode.WsInvestigator];'))
    p.write_text(s); print('patched')

if __name__ == '__main__':
    main(sys.argv[1])
