"""Opt-in discipline pack: an advisory nudge when the same shell command keeps failing. It never blocks."""
import json
import re
import shlex

from . import core

LIMIT = 3  # failures of one command in one session before the nudge
NUDGE = (f'This command has now failed {LIMIT} times in this session. Stop retrying it as is: read the error, write down one '
         'hypothesis and change one thing. If the approach is a dead end, tell the user and save it so the next session '
         'skips it: ws checkpoint <task> --status in_progress --next "<next step>" --note "Do not redo=<approach: why it failed>".')


def failed(payload):
    """True for a shell command that ran and exited non-zero (Claude PostToolUseFailure, Codex PostToolUse)."""
    if payload.get('hook_event_name') == 'PostToolUseFailure':  # Claude: the error starts with "Exit code N"
        match = re.match(r'\s*Exit code (\d+)', str(payload.get('error', '')))
        return bool(match) and match[1] != '0'
    response = payload.get('tool_response')
    code = response.get('exit_code', response.get('exitCode')) if isinstance(response, dict) else None
    if code is None:  # ponytail: Codex sends a plain string; the exit-code wording is matched loosely until a live check pins it
        match = re.search(r'(?i)\bexit(?:ed with)?(?: code|_code)\b\W{0,3}(-?\d+)', str(response)[:2000])
        code = int(match[1]) if match else 0
    return isinstance(code, int) and code != 0


def hook(root, payload):
    if payload.get('tool_name') != 'Bash' or not isinstance(payload.get('tool_input'), dict) or not failed(payload): return {}
    command = payload['tool_input'].get('command', '')
    if isinstance(command, list): command = shlex.join(map(str, command))
    if not isinstance(command, str) or not command.strip(): return {}
    path = core.inside(root / '.ws' / 'discipline' / (core.digest_text(str(payload.get('session_id', '')))[:16] + '.json'), [root])
    try: counts = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): counts = {}
    if not isinstance(counts, dict): counts = {}
    key = core.digest_text(' '.join(command.split()))[:16]  # the command itself is not stored
    counts[key] = int(counts.get(key, 0)) + 1 if isinstance(counts.get(key, 0), int) else 1
    path.parent.mkdir(parents=True, exist_ok=True); core.atomic_write(path, json.dumps(counts) + '\n')
    if counts[key] != LIMIT: return {}  # once per command, at the third failure
    return {'hookSpecificOutput': {'hookEventName': payload['hook_event_name'], 'additionalContext': NUDGE}}
