"""Size-only, opt-in advice; never persist or replace a tool response."""
import json
from . import core


def hook(root, payload):
    packs = core.config(root).get('packs', [])
    if not isinstance(packs, list) or 'digest' not in packs or not isinstance(payload, dict): return {}
    if payload.get('hook_event_name') != 'PostToolUse' or 'tool_response' not in payload: return {}
    response = payload['tool_response']
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, separators=(',', ':'))
    size = len(text.encode('utf-8'))
    if size <= 40000: return {}
    message = f'Tool output is {size} bytes. If it is saved in a workspace or linked repo file, use ws digest <file> or the digest_file MCP tool before rereading the full output.'
    return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': message}}
