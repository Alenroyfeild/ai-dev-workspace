"""Optional plugin entrypoints; inactive outside a validated ws-started repo."""
import argparse
import io
import json
import os
import sys
from pathlib import Path
from . import core


EVENTS = {'SessionStart': 'brief', 'PreCompact': 'nudge', 'Stop': 'nudge', 'UserPromptSubmit': 'paste', 'PreToolUse': 'guard',
          'sessionStart': 'brief', 'preCompact': 'nudge', 'stop': 'nudge', 'sessionEnd': 'nudge', 'beforeSubmitPrompt': 'paste', 'preToolUse': 'guard'}  # Cursor's are camelCase
REPO_HOOKS = {'codex': '.codex/hooks.json', 'cursor': '.cursor/hooks.json'}  # the file ws start writes for a client whose plugin ships the same hooks
GUARDED = ('codex', 'cursor')  # Claude's guard is a repo hook of the guards pack


def linked_repo(start=None):
    base = Path(start or os.getcwd()).resolve()
    for candidate in (base, *base.parents):
        if (candidate / '.ws-start.json').is_file():
            return candidate
    return None


def workspace(start=None):
    # Plugin processes must not inherit unrelated memory through WS_ROOT.
    repo = linked_repo(start)
    return core.find_root(repo) if repo else None


def repo_wired(client, repo, event):
    """True when ws start wrote this client's repo hooks and they already handle the event, so the plugin must not run it too."""
    relative = REPO_HOOKS.get(client)
    try:
        files = json.loads((repo / '.ws-start.json').read_text(encoding='utf-8-sig')).get('files')
        return bool(relative and isinstance(files, dict) and relative in files
                    and event in json.loads((repo / relative).read_text(encoding='utf-8-sig')).get('hooks', {}))
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def main(argv=None):
    from . import cli
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', choices=('claude', 'codex', 'cursor'), required=True)
    args = parser.parse_args(argv)
    event = None
    try:
        text = cli._read_limited_stdin()
        payload = core.json_loads(text)
        if not isinstance(payload, dict): raise ValueError('Expected an object')
        cwd = payload.get('cwd')
        roots = payload.get('workspace_roots')  # Cursor's common payload has no cwd
        if cwd is None and isinstance(roots, list) and roots and isinstance(roots[0], str) and roots[0]: cwd = roots[0]
        if cwd is not None and (not isinstance(cwd, str) or not cwd): raise ValueError('Invalid cwd')
        event = payload.get('hook_event_name')
        command = EVENTS.get(event)
        if command == 'guard' and args.client not in GUARDED: command = None
        repo = linked_repo(cwd) if command else None
        root = core.find_root(repo) if repo else None
        # Never double-run: ws start's own hook wins; the guard is the opt-in guards pack, never a plugin default.
        if root and (repo_wired(args.client, repo, event) or command == 'guard' and 'guards' not in core.config(root).get('packs', [])):
            root = None
    except (core.WsError, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(f'ws: hook skipped ({type(exc).__name__}: {str(exc)[:200]})', file=sys.stderr)  # fail open, like the other hooks
        root = None
    if root is None:
        # Cursor treats unreadable or empty preToolUse output as a block, so a skipped guard still has to say allow.
        print(json.dumps({'permission': 'allow'} if args.client == 'cursor' and event in (None, 'preToolUse') else {})); return 0
    previous = sys.stdin
    try:
        sys.stdin = io.StringIO(text)
        return cli.main(['--workspace-root', str(root), command, '--hook', '--client', args.client])
    finally:
        sys.stdin = previous
