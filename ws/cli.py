"""`ws` command line. Every command prints JSON or plain text and exits non-zero on error."""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import core, assist, orchestration, native, workers, upgrade


def _read_limited_stdin():
    limit = core.MAX_READ_BYTES
    stream = getattr(sys.stdin, 'buffer', None)
    if stream is not None:
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise core.WsError('Input exceeds 50 MB.')
        try: return raw.decode('utf-8')
        except UnicodeDecodeError: raise core.WsError('Paste input must be UTF-8 text.')
    text = sys.stdin.read(limit + 1)
    try: size = len(text.encode('utf-8'))
    except UnicodeEncodeError: raise core.WsError('Paste contains text that cannot be saved as UTF-8.')
    if len(text) > limit or size > limit:
        raise core.WsError('Input exceeds 50 MB.')
    return text


def _block_prompt(client, reason):
    if client == 'claude':
        print(reason, file=sys.stderr); return 2
    if client == 'cursor': out({'continue': False, 'user_message': reason})
    elif client == 'gemini': out({'decision': 'deny', 'reason': reason})
    else: out({'decision': 'block', 'reason': reason})
    return 0


DAILY_COMMANDS = ('start', 'status', 'task', 'claim', 'checkpoint', 'remember', 'search', 'lesson', 'doctor')


class GroupedHelpFormatter(argparse.HelpFormatter):
    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction) and action.dest == 'cmd':
            choices = {item.dest: item for item in action._choices_actions}
            output = [' ' * self._current_indent + 'Daily:\n']
            self._indent()
            output.extend(argparse.HelpFormatter._format_action(self, choices[name])
                          for name in DAILY_COMMANDS if name in choices)
            self._dedent()
            return ''.join(output)
        return super()._format_action(action)


def human():
    return sys.stdout.isatty() and not os.environ.get('WS_JSON')


def readable(value, indent=''):
    """Plain key: value lines for people; scripts get JSON (piped output or WS_JSON=1)."""
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, dict) and item or isinstance(item, list) and not all(isinstance(i, (str, int, float, bool)) for i in item):
                lines.append(f'{indent}{key}:'); lines.append(readable(item, indent + '  '))
            elif isinstance(item, (list, dict)):
                lines.append(f"{indent}{key}: {', '.join(map(str, item)) or 'none'}")
            else:
                lines.append(f"{indent}{key}: {'yes' if item is True else 'no' if item is False else item}")
        return '\n'.join(lines)
    if isinstance(value, list):
        return '\n'.join(readable(item, indent + '  ').replace(indent + '  ', indent + '- ', 1) if isinstance(item, dict)
                         else f'{indent}- {item}' for item in value) or indent + 'none'
    return f'{indent}{value}'


def out(value):
    print(value if isinstance(value, str) else readable(value) if human() else json.dumps(value, indent=2, ensure_ascii=False))


def show(plan, summary):
    """A terminal gets a few readable lines to approve; scripts and pipes keep the full JSON plan."""
    out(summary(plan) if human() else plan)


def text_status(report):
    lines = [f"Workspace: {report['workspace']}"]
    tasks = ', '.join(f'{name} {count}' for name, count in sorted(report['tasks'].items())) or 'none'
    lines.append('Tasks: ' + tasks)
    for label, key in (('Active claims', 'active_claims'), ('Blocked', 'blocked')):
        lines.append(label + ': ' + ('; '.join(report[key]) or 'none'))
    lines.extend(f'Conflicted: {hint}' for hint in report.get('conflicted', []))
    lines.extend((f"Open feedback: {report['open_feedback']}", f"Lessons: {report['lessons']}",
                  f"Recent runs: {report['runs']['steps']}"))
    if 'codex_goals' in report:
        lines.append(f"Codex goals: {report['codex_goals']['active']} active, {report['codex_goals']['complete']} complete")
    return '\n'.join(lines)


def text_route(report):
    model = f" / {report['model']}" if report.get('model') else ''
    lines = [f"Role: {report['role']}", f"Provider: {report['provider']}{model}",
             'Available: ' + ('yes' if report['available'] else 'no')]
    if report.get('reason'):
        lines.append('Reason: ' + report['reason'])
    if report.get('model_source'):
        lines.append('Model source: ' + report['model_source'])
    if report.get('model_warning'):
        lines.append('Model warning: ' + report['model_warning'])
    if report.get('skipped'):
        lines.append('Skipped: ' + '; '.join(f"{item['provider']} ({item['reason']})" for item in report['skipped']))
    return '\n'.join(lines)


def text_doctor(report):
    core = report.get('core', {})
    lines = [f"Core: Python 3 {'available' if core.get('python3') else 'missing'}, Git {'available' if core.get('git') else 'missing'}"]
    if report.get('workspace'):
        lines.append(f"Workspace: {report['workspace']} ({'valid' if report.get('valid') else 'invalid'})")
    if report.get('team_workspace'):
        pulls = 'enabled (read-only)' if report['team_workspace'].get('auto_pull') is True else 'off (consent required)'
        lines.append('Team privacy: ' + report['team_workspace']['privacy'] + '; automatic pulls ' + pulls)
        if report['team_workspace'].get('problem'): lines.append('Team problem: ' + report['team_workspace']['problem'])
    if report.get('setup'):
        assistants = ', '.join(report['setup']['assistants'])
        lines.append('Setup preset: ' + report['setup']['preset'] + (f' ({assistants})' if assistants else ''))
    for path in report.get('codex_manual_pending', []): lines.append('Codex: manual step pending — ' + path)
    for item in report.get('stale_hooks', []): lines.append(f"Hooks point to a missing kit or workspace — {item['repo']}/{item['file']}: {item['missing']}; run ws start again in that repo (if you edited that file, ws start --undo then ws start)")
    clients = report.get('configured_clients', {})
    if clients:
        lines.append('Workspace-level connections: ' + (', '.join(name for name, configured in clients.items() if configured) or 'none'))
    goals = report.get('codex_goals')
    if goals:
        lines.append(f"Codex goals: {goals['active']} active, {goals['complete']} complete" if 'active' in goals
                     else f"Codex goals: skipped ({goals['skipped']})")
    lines.extend(f'Conflicted: {hint}' for hint in report.get('conflicted', []))
    lines.extend(f'Team: {warning}' for warning in report.get('team', {}).get('warnings', []))
    health = report.get('capture_health')
    if health:
        outcome = health.get('outcome', 'unknown')
        detail = [health[k] for k in ('client', 'date') if health.get(k)] + ([health['reason']] if health.get('reason') not in (None, outcome) else [])
        lines.append('Last capture: not run yet' if outcome == 'not_run' else f'Last capture outcome: {outcome}' + (f" ({', '.join(detail)})" if detail else ''))
    checks = report.get('protocol_checks', {})
    if checks:
        rendered = [f"{name}={value['status']}" + (f" ({value['step']})" if value.get('step') else '')
                    for name, value in checks.items()]
        date = report.get('protocol_check_date', 'unknown')
        lines.append('Last protocol check: ' + ', '.join(rendered) + f' (date: {date})')
    routes = report.get('routes', {})
    if routes:
        rendered = [f"{name}={value['provider']} ({'available' if value.get('available') else 'unavailable'})"
                    for name, value in routes.items() if isinstance(value, dict) and 'provider' in value]
        lines.append('Routes: ' + (', '.join(rendered) or routes.get('error', 'unavailable')))
    if report.get('mcp_tools'):
        tools = report['mcp_tools']
        lines.append(f"MCP tools listed: {tools['listed']} ({tools['profile']}; set \"mcp_tools\": \"all\" in workspace.json to list every tool)")
    missing = [item['name'] for item in report.get('toolbox', [])]
    lines.append('Missing recommended tools: ' + (', '.join(missing) or 'none'))
    if 'mcp' in report:
        lines.append('MCP checks: ' + (', '.join(f"{item['client']} {'ok' if item['ok'] else 'failed'}" for item in report['mcp']) or 'none configured'))
    return '\n'.join(lines)


def collision_notices(result):
    for message in result.get('collisions', []):
        print(message, file=sys.stderr)


def claude_tool_calls(transcript_path):
    """Return Claude Code tool-use count, or None when the transcript is unusable."""
    uses = claude_tool_uses(transcript_path)
    return None if uses is None else len(uses)


def claude_tool_uses(transcript_path):
    """Return Claude Code tool_use blocks, or None when the transcript is unusable."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    path = Path(transcript_path)
    try:
        if path.stat().st_size > 50 * 1024 * 1024:
            return None
        transcript = path.open(encoding='utf-8', errors='replace')
    except OSError:
        return None
    recognized = False
    uses = []
    try:
        with transcript:
            for line in transcript:
                try:
                    entry = json.loads(line)
                    content = entry['message']['content'] if entry.get('type') == 'assistant' else None
                except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
                    continue
                if not isinstance(content, list):
                    continue
                recognized = True
                uses += [item for item in content if isinstance(item, dict) and item.get('type') == 'tool_use']
    except OSError:
        return None
    return uses if recognized else None


def unrecorded_work(root, uses):
    """Ask once for a checkpoint when this session edited files but never updated its task."""
    def recorded(use):
        name, data = str(use.get('name', '')), use.get('input') if isinstance(use.get('input'), dict) else {}
        return (name.endswith('__checkpoint') or name == 'Skill' and data.get('skill') == 'handoff'
                or name == 'Bash' and 'ws checkpoint' in str(data.get('command', '')))
    if not any(use.get('name') in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit') for use in uses) or any(map(recorded, uses)):
        return ''
    task = core.sole_local_claim(root)
    return (f'Files changed this session but {task} was not updated. Before stopping, run '
            f'`ws checkpoint {task} --status in_progress|review|done --next "<exact next action>"` '
            f'(done if the task is finished). Skip only if these edits were unrelated to {task}.') if task else ''


def mcp_main():
    """Console script `ai-dev-workspace`: the stdio MCP server, for uvx and MCP registry launchers."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('ws_mcp_server', core.KIT / 'mcp' / 'server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)  # by path: a top-level 'mcp' import could pick up the unrelated MCP SDK
    server.main()


def ask(prompt=''):
    """y/N answer; a closed stdin is "no confirmation", not a traceback."""
    try: return input(prompt).strip().lower() in ('y', 'yes')
    except EOFError: raise core.WsError('No confirmation; use --yes or --dry-run.')


class WsParser(argparse.ArgumentParser):
    """Subparsers inherit this class: a mistyped command gets a short hint, not argparse's list of every name."""
    def error(self, message):
        bad = re.search(r"invalid choice: '(.*?)' \(choose from (.*)\)$", message)
        if not bad: return super().error(message)
        choices = [c.strip("'") for c in bad[2].split(', ')]
        near = difflib.get_close_matches(bad[1], choices, n=3)
        top = self.prog == 'ws'
        hint = f'; did you mean: {", ".join(near)}?' if near else ('. Run ws --help' if top else f'. Choose from: {", ".join(choices)}')
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: unknown {'command' if top else 'choice'} '{bad[1]}'{hint}" + (' Run ws --help' if top and near else '') + '\n')


def main(argv=None):
    if core.WINDOWS:  # the pip/pipx `ws` script skips bin/ws, whose cp1252 pipes cannot carry non-ASCII text
        for stream in (sys.stdin, sys.stdout, sys.stderr): getattr(stream, 'reconfigure', lambda **_: None)(encoding='utf-8')
    p = WsParser(prog='ws', description='AI Dev Workspace: shared memory and coordination for AI-assisted development.',
                 formatter_class=GroupedHelpFormatter,
                 epilog='More: `ws help all` lists every command; `ws <command> --help` shows its options.')
    p.add_argument('--version', action='version', version=f"%(prog)s {core.kit_meta()['version']}")
    p.add_argument('--workspace-root', help='explicit workspace directory (also used by generated hooks)')
    sub = p.add_subparsers(dest='cmd', required=True, title='Commands', metavar='COMMAND')
    sub.add_parser('demo', help='try remembered decisions offline in a disposable workspace')

    s = sub.add_parser('init', help='create a workspace')
    s.add_argument('dir'); s.add_argument('--name')
    s.add_argument('--pack', action='append', default=[], help=f'domain pack: {", ".join(core.available_packs())}')
    s.add_argument('--repo', action='append', default=[], help='code checkout this workspace serves')
    sub.add_parser('packs', help='list available packs')
    s = sub.add_parser('tools', help='list local tools and load estimates'); s.add_argument('--cost', action='store_true')
    s = sub.add_parser('pack', help='plug a pack into this workspace'); s.add_argument('action', choices=['add', 'remove']); s.add_argument('name', nargs='?')
    s.add_argument('--from', dest='source', help='private pack folder (kept outside the kit)')
    s = sub.add_parser('status', help='workspace overview'); s.add_argument('--text', action='store_true', help='show a human-readable summary')
    s = sub.add_parser('route', help='resolve an explicit role binding; PATH availability only'); s.add_argument('role', nargs='?', default='lead'); s.add_argument('--text', action='store_true', help='show a human-readable summary')
    s = sub.add_parser('delegate', help='prepare bounded work or test the read-only worker'); s.add_argument('task', nargs='?'); s.add_argument('--role'); s.add_argument('--run', action='store_true')
    s.add_argument('--selftest', action='store_true'); s.add_argument('--provider', choices=('codex', 'claude'))
    s.add_argument('--diff', help='reviewer-only Git range, e.g. HEAD~1..HEAD')
    w = sub.add_parser('worker', help='prepare an isolated implementation checkout; no worker launch').add_subparsers(dest='action', required=True)
    s = w.add_parser('prepare'); s.add_argument('task'); s.add_argument('--scope', action='append', required=True)
    s.add_argument('--base', default='HEAD'); s.add_argument('--dry-run', action='store_true'); s.add_argument('--yes', action='store_true')
    s = w.add_parser('launch', help='gated until the real-client hostile probe passes'); s.add_argument('id')
    s = w.add_parser('review', help='show diff/checks or record the current lead review'); s.add_argument('id')
    s.add_argument('--approve', action='store_true'); s.add_argument('--yes', action='store_true')
    for action in ('accept', 'discard'):
        s = w.add_parser(action); s.add_argument('id'); s.add_argument('--dry-run', action='store_true'); s.add_argument('--yes', action='store_true')
    sub.add_parser('validate', help='check task records, links and secrets')
    s = sub.add_parser('doctor', help='check which tools are installed'); s.add_argument('--mcp', action='store_true', help='run project MCP connection checks'); s.add_argument('--text', action='store_true', help='show a human-readable summary')
    s = sub.add_parser('audit', help="score this repo's AI assistant setup and list the top fixes (read-only)"); s.add_argument('repo', nargs='?'); s.add_argument('--text', action='store_true', help='show a human-readable summary')
    s = sub.add_parser('guard', help='guards pack: PreToolUse check that denies destructive commands, secrets and muted tests'); s.add_argument('--hook', action='store_true'); s.add_argument('--client', default='claude')
    s = sub.add_parser('discipline', help='discipline pack: advisory nudge after the same command fails 3 times'); s.add_argument('--hook', action='store_true'); s.add_argument('--client', default='claude')
    s = sub.add_parser('map', help='write a compact codebase map'); s.add_argument('repo', nargs='?')
    s = sub.add_parser('connect', help='connect an assistant to this workspace')
    s.add_argument('client', choices=('claude', 'codex', 'cursor', 'copilot', 'vscode', 'gemini'))
    s.add_argument('--write', action='store_true', help='append Codex global config with a backup')
    s.add_argument('--skills', action='store_true', help='also link the kit skills into your global ~/.claude/skills or ~/.agents/skills')
    s = sub.add_parser('start', help='connect this repo to private memory outside the checkout')
    s.add_argument('--yes', action='store_true', help='apply the printed preview without prompting')
    s.add_argument('--dry-run', action='store_true', help='preview without writing anything')
    s.add_argument('--workspace', help='private workspace folder (default ~/.ai-dev-workspace/<repo-name>)')
    s.add_argument('--undo', action='store_true', help='remove unchanged repo wiring; keep private memory')
    s.add_argument('--memory-dir', help='Claude auto-memory directory to preview for import')
    s.add_argument('--no-import', action='store_true', help='skip existing memory import')
    s = sub.add_parser('scope', help='read or change local record sharing eligibility; never publishes')
    s.add_argument('item'); s.add_argument('value', nargs='?', choices=('private', 'team'))
    s.add_argument('--expected-sha', help='refuse if the record changed since inspection')
    for command in ('share', 'unshare'):
        s = sub.add_parser(command, help='preview a local team copy or its removal')
        s.add_argument('item'); s.add_argument('--author')
        s.add_argument('--as', dest='as_format', choices=('runbook',), default='')
        s.add_argument('--dry-run', action='store_true'); s.add_argument('--yes', action='store_true')
    s = sub.add_parser('sync', help='pull team updates and preview an approved-only push')
    s.add_argument('--dry-run', action='store_true', help='pull and preview; never commit or push')
    s.add_argument('--yes', action='store_true', help='approve the exact printed preview')
    mode = s.add_mutually_exclusive_group()
    mode.add_argument('--pull-only', action='store_true', help='read-only Git pull; never publish')
    mode.add_argument('--daily', metavar='HH:MM', help='preview a daily read-only scheduler')
    s.add_argument('--automatic', action='store_true', help=argparse.SUPPRESS)
    s = sub.add_parser('team', help='preview or link a private team Git repository')
    s.add_argument('action', choices=('init', 'link', 'unlink', 'status')); s.add_argument('remote', nargs='?', default='')
    s.add_argument('--folder', action='store_true', help='link an attested existing synced folder (read-only)')
    s.add_argument('--dry-run', action='store_true'); s.add_argument('--yes', action='store_true')
    s.add_argument('--attest-private', action='store_true', help='I confirm this exact remote is private to my team')
    s.add_argument('--verify-with', choices=('gh', 'glab'), default='')
    s.add_argument('--author', default='local', help='portable alias for a status snapshot')
    status_mode = s.add_mutually_exclusive_group()
    status_mode.add_argument('--publish-status', action='store_true', help='opt in to previewed status saves')
    status_mode.add_argument('--disable-status', action='store_true', help='turn off status and preview removal of this alias')
    pulls = s.add_mutually_exclusive_group()
    pulls.add_argument('--auto-pull', dest='auto_pull', action='store_true', default=None)
    pulls.add_argument('--no-auto-pull', dest='auto_pull', action='store_false')
    s = sub.add_parser('setup', help='choose assistants and configure project connections')
    s.add_argument('--assistants', help='comma-separated assistants; no client is launched')
    s.add_argument('--preset', help='routing preset name')
    s.add_argument('--detect', action='store_true', help='read-only CLI/app detection, no workspace needed')
    choice = s.add_mutually_exclusive_group()
    choice.add_argument('--dry-run', action='store_true', help='preview only (default)')
    choice.add_argument('--apply', action='store_true', help='apply the previewed preset and project connections')

    t = sub.add_parser('task', help='task records').add_subparsers(dest='action', required=True)
    s = t.add_parser('new', help='create a task record'); s.add_argument('id', help='short ID such as JIRA-123 or fix-login'); s.add_argument('title')
    s.add_argument('--objective', default='', help='one-line goal'); s.add_argument('--branch', default='', help='Git branch the task belongs to'); s.add_argument('--repo', default='', help='repo path the task belongs to')
    t.add_parser('list', help='list tasks with status, claim and next action')
    s = t.add_parser('find', help='find tasks by ID, branch or title'); s.add_argument('ref', help='ID, branch or title text')
    s = t.add_parser('show', help='print one task record'); s.add_argument('id'); s.add_argument('--section', action='append', help='print only this section; repeat for several')
    s = t.add_parser('depend', help='make a task wait for another'); s.add_argument('id'); s.add_argument('--on', required=True, metavar='OTHER')
    s = t.add_parser('import', help='create tasks from Task Master tasks.json or a Spec Kit tasks.md (preview unless --yes)')
    s.add_argument('file'); s.add_argument('--prefix', default='SPEC'); s.add_argument('--yes', action='store_true', help='write the tasks')
    s = sub.add_parser('next', help='open tasks whose dependencies are done'); s.add_argument('--json', action='store_true')

    s = sub.add_parser('claim', help='claim a task'); s.add_argument('id'); s.add_argument('--worker', help='label for this session (default: $USER)')
    s = sub.add_parser('release', help='release a task claim'); s.add_argument('id')
    s.add_argument('--worker', help='default: the worker that claimed it here'); s.add_argument('--token', help='default: the token saved by ws claim')
    valid_notes = ', '.join(core.NOTE_SECTIONS)
    s = sub.add_parser('checkpoint', help='save task status and next action',
                       description='Save task status, next action, and optional notes.',
                       epilog='Valid note sections: ' + valid_notes)
    s.add_argument('id', help='task ID (see ws task list)'); s.add_argument('--status', required=True, choices=core.STATUSES)
    s.add_argument('--next', required=True, help='exactly what the next person or AI should do')
    s.add_argument('--expected-sha', help='refuse if the task changed since you read it'); s.add_argument('--worker', help='default: the worker that claimed it here'); s.add_argument('--token', help='default: the token saved by ws claim')
    s.add_argument('--note', action='append', default=[], metavar='SECTION=TEXT', help='save text into a section, e.g. "Handoff=Decision: use Postgres"; repeatable')

    s = sub.add_parser('remember', help='save one decision in the current task for the next session')
    s.add_argument('text', help='the decision, e.g. "use Postgres, not SQLite"'); s.add_argument('--task', metavar='ID', help='task to save into (default: your only claimed task)')
    s.add_argument('--team', action='store_true', help='also preview sharing it with the linked team'); s.add_argument('--yes', action='store_true', help='apply the team preview without asking'); s.add_argument('--author', help='name for the team copy')
    s = sub.add_parser('pr-notes', help="print the task's decisions and checks as a PR-description block")
    s.add_argument('id', nargs='?', help='task (default: your only claimed task or the current branch task)')
    s.add_argument('--no-link', action='store_true', help='omit the one-line ai-dev-workspace credit')
    s.add_argument('--json', action='store_true', help='print JSON instead of Markdown')
    s = sub.add_parser('recap', help='tasks, decisions and team notes since a date (for standups and handoffs)')
    s.add_argument('--since', default='7d', help='7d (days back) or YYYY-MM-DD; default 7d')
    s.add_argument('--json', action='store_true', help='print JSON instead of Markdown')
    k = sub.add_parser('know', help='save or read categorized knowledge').add_subparsers(dest='action', required=True)
    s = k.add_parser('add', help='save one knowledge entry')
    s.add_argument('text'); s.add_argument('--team', action='store_true', help='also preview sharing it with the linked team'); s.add_argument('--yes', action='store_true', help='apply the team preview without asking'); s.add_argument('--author', help='name for the team copy')
    s.add_argument('--category', default='other', help='product, feature, domain, repo, runbook or other (default other)')
    s = k.add_parser('list', help='list knowledge entries'); s.add_argument('--category', default='', help='only this category'); s.add_argument('--layer', choices=('all', 'private', 'team'), default='all')
    s = k.add_parser('show', help='print one knowledge entry'); s.add_argument('id', help='ID from ws know list')

    s = sub.add_parser('search', help='ranked vault search (snippets, not whole files)'); s.add_argument('query', help='words to look for (3+ letters)'); s.add_argument('--category', default='', help='only knowledge in this category')
    sessions = sub.add_parser('sessions', help='search local assistant transcripts').add_subparsers(dest='action', required=True)
    s = sessions.add_parser('search', help='search transcripts of earlier assistant sessions'); s.add_argument('query')
    s.add_argument('--root', action='append', metavar='CLIENT=DIR', help='search explicit transcript directories instead of defaults')
    s = sub.add_parser('import', help='preview or import assistant-native memories (read-only)').add_subparsers(dest='action', required=True).add_parser('native')
    s.add_argument('--client', choices=(*native.CLIENTS, 'all'), default='all'); s.add_argument('--task'); s.add_argument('--yes', action='store_true')
    l = sub.add_parser('lesson', help='add or search reusable lessons').add_subparsers(dest='action', required=True)
    s = l.add_parser('add', help='save a lesson: what happened -> rule'); s.add_argument('text'); s.add_argument('--tag', action='append', default=[], help='topic tag; repeatable')
    s.add_argument('--team', action='store_true', help='also preview sharing it with the linked team'); s.add_argument('--yes', action='store_true', help='apply the team preview without asking'); s.add_argument('--author', help='name for the team copy')
    s.add_argument('--path', action='append', default=[], help='relative repo glob; repeat for multiple paths'); s.add_argument('--area', default='')
    s = l.add_parser('search', help='find saved lessons'); s.add_argument('query', nargs='?', default='', help='words to look for (default: all)')
    f = sub.add_parser('feedback', help='record or submit product feedback').add_subparsers(dest='action', required=True)
    s = f.add_parser('add', help='record feedback locally'); s.add_argument('text'); s.add_argument('--kind', default='idea', help='idea, bug, praise or friction (default idea)'); s.add_argument('--source', default='user')
    s = f.add_parser('list', help='list feedback items'); s.add_argument('--all', action='store_true', help='include items already done')
    s = f.add_parser('submit', help='turn item N into a GitHub issue (preview first)'); s.add_argument('n', type=int); s.add_argument('--yes', action='store_true')
    s = f.add_parser('link', help='record the issue URL for item N'); s.add_argument('n', type=int); s.add_argument('url')
    f.add_parser('sync', help='tick items whose issue is closed')
    s = sub.add_parser('update', help='check for or install a new kit release'); s.add_argument('--check', action='store_true')
    sub.add_parser('version', help='print the installed kit version')
    s = sub.add_parser('upgrade', help='preview or apply managed workspace updates'); s.add_argument('--dry-run', action='store_true', help='print the changes without writing them'); s.add_argument('--diff', action='store_true', help='show the full diff of every file, not the summary')
    sub.add_parser('notices', help='updates, fixed issues and unshared feedback worth mentioning')
    s = sub.add_parser('assist', help='suggest improvements; apply only after explicit permission')
    s.add_argument('action', nargs='?', choices=('apply', 'decide')); s.add_argument('id', nargs='?')
    s.add_argument('decision', nargs='?', choices=('accepted', 'declined', 'snoozed', 'always')); s.add_argument('--until')
    for command in ('brief', 'nudge'):
        s = sub.add_parser(command, help='local task memory for assistant sessions')
        s.add_argument('--hook', action='store_true', help='consume assistant hook input on stdin')
        s.add_argument('--client', choices=('claude', 'codex', 'cursor', 'gemini', 'vscode'), default='claude')
        if command == 'brief': s.add_argument('--refresh', action='store_true', help='also update the current-task block in client instruction files')
    s = sub.add_parser('digest', help='summarise a big log/JSON file deterministically'); s.add_argument('file')
    s.add_argument('--focus', help='show regex-matching line prefixes before the summary (bounded regex; 4096 chars/line)')
    s.add_argument('--local-summary', action='store_true', help='also use the configured local-llm pack')
    s = sub.add_parser('paste', help='save clipboard or stdin to the private inbox and show its digest')
    s.add_argument('--hook', action='store_true', help=argparse.SUPPRESS)
    s.add_argument('--client', choices=('claude', 'codex', 'cursor', 'gemini'), default='claude')
    r = sub.add_parser('run', help='orchestration step tracking').add_subparsers(dest='action', required=True)
    s = r.add_parser('log'); s.add_argument('task'); s.add_argument('step'); s.add_argument('--provider', required=True)
    s.add_argument('--model', default=''); s.add_argument('--tokens-in', type=int, default=0); s.add_argument('--tokens-out', type=int, default=0)
    s.add_argument('--seconds', type=float, default=0); s.add_argument('--result', default='ok'); s.add_argument('--note', default='')
    s.add_argument('--worker-role', default=''); s.add_argument('--effort', default='')
    s.add_argument('--check', action='append', default=[]); s.add_argument('--files', type=int)
    s.add_argument('--verdict', choices=('accepted', 'changes', 'rejected'), default=''); s.add_argument('--findings', type=int)
    s = r.add_parser('report'); s.add_argument('task', nargs='?')
    s = r.add_parser('import'); s.add_argument('source', choices=('codeburn',)); s.add_argument('--since'); s.add_argument('--task')
    s = sub.add_parser('trace', help='read-only Markdown timeline of reported orchestration steps'); s.add_argument('task')

    args = sys.argv[1:] if argv is None else argv
    if args == ['help', 'all']:
        p.formatter_class = argparse.HelpFormatter
        p.print_help()
        return 0
    if args in (['--help'], ['-h'], ['help']):
        p.usage = '%(prog)s [options] {' + ','.join(DAILY_COMMANDS) + '}'
    if args == ['help']:
        p.print_help()
        return 0
    a = p.parse_args(argv)
    try:
        if a.cmd == 'demo':
            from . import demo
            if a.workspace_root: raise core.WsError('ws demo uses its own disposable workspace; omit --workspace-root.')
            out(demo.run()); return 0
        if a.cmd == 'start':
            from . import repo
            if a.workspace_root: raise core.WsError('Run ws start inside the code repo; no --workspace-root is needed.')
            try: result = repo.start(a.yes, a.dry_run, a.workspace, a.undo, a.memory_dir, a.no_import)
            except core.WsError: raise  # already says what to do; the prefix below is for unexpected file errors
            except (OSError, ValueError) as exc: raise core.WsError('Repo setup stopped; review local files before retrying: ' + str(exc))
            if result and result.get('undone'):
                print(('Kept edited repo wiring; ' if result.get('partial') else 'Removed repo wiring; ') + 'private memory kept at ' + result['root'])
                return 2 if result.get('partial') else 0
            if result:
                print(('Partial setup: ' if result.get('partial') else 'Already set up: ' if result['already'] else 'Set up: ') + result['root'] + '; assistants: ' + (', '.join(result['assistants']) or 'none detected') + ('; Codex: ' + result.get('codex_status', 'connected')))
                print('Open this repo in Claude or Codex as usual; trust local hooks/MCP when asked.')
                print('Next: ' + ('task ' + result['task'] if result['task'] else 'no saved task') + ' (' + result['branch'] + '); work normally and save a checkpoint before stopping.')
                if result.get('starter'): print(f"Looks like {repo.STARTERS[result['starter']]}: ws pack add {result['starter']} adds a few starter rules (optional).")
            return 2 if result and result.get('partial') else 0
        if a.cmd == 'setup' and a.detect:
            from . import setup
            if a.assistants is not None or a.preset: raise core.WsError('--detect cannot configure assistants.')
            out(setup.detect()); return 0
        if a.cmd == 'init':
            cfg = core.init(a.dir, a.name or Path(a.dir).expanduser().resolve().name, a.pack, a.repo)
            collision_notices(cfg)
            for connection in cfg.get('connections', []):
                if connection['client'] == 'codex':
                    print('codex: not connected yet; run `ws connect codex` if you use Codex.')
                else:
                    print(f"{connection['client']}: {connection.get('note', 'already connected')}")
            out(f"Workspace '{cfg['name']}' created in {Path(a.dir).resolve()} (packs: {', '.join(cfg['packs']) or 'none'}).\n"
                f"Next: cd {a.dir} && ws connect claude   (or codex, cursor, vscode, gemini)\n"
                f"Then: ws task new <ID> \"<title>\" && ws claim <ID>   — guide: docs/SETUP.md")
            return 0
        if a.cmd == 'packs':
            out({n: core.pack_manifest(n)['description'] for n in core.available_packs()}); return 0
        if a.cmd == 'tools':
            try:
                root = core.find_root(a.workspace_root)
            except core.WsError:
                root = None
            out(core.tool_costs(root) if a.cost else core.tools(root)); return 0
        if a.cmd == 'version':
            out(core.kit_meta()['version']); return 0
        if a.cmd == 'update':
            if core.PACKAGED and not a.check:
                out(core.update_kit()); return 0
            res = core.check_update(force=True)
            if a.check or not res.get('update_available'):
                out(res); return 0
            out(core.update_kit()); return 0
        if a.cmd == 'doctor':
            try:
                root = core.find_root(a.workspace_root)
            except core.WsError:
                root = None
            report = core.doctor(root, a.mcp)
            out(text_doctor(report) if a.text or human() else report); return 0
        if a.cmd == 'audit':
            from . import audit
            report = audit.audit(a.repo)
            out(audit.text(report) if a.text or human() else report); return 0
        if a.cmd == 'guard':  # no workspace lookup: runs before every tool call, and any error must allow the call
            from . import guards
            try: payload = json.load(sys.stdin)
            except ValueError: payload = {}
            print(json.dumps(guards.hook(payload if isinstance(payload, dict) else {}))); return 0
        if a.cmd == 'discipline':  # advisory only: any error prints {} so the tool result reaches the model unchanged
            from . import discipline
            try:
                payload = json.load(sys.stdin)
                result = discipline.hook(core.find_root(a.workspace_root), payload) if isinstance(payload, dict) and payload.get('hook_event_name') in ('PostToolUse', 'PostToolUseFailure') else {}
            except (ValueError, OSError, core.WsError): result = {}
            print(json.dumps(result)); return 0
        if a.cmd == 'sessions':
            roots = None
            if a.root:
                roots = {}
                for value in a.root:
                    client, separator, directory = value.partition('=')
                    if client not in ('claude', 'codex', 'cursor', 'gemini') or not separator or not directory:
                        raise core.WsError('Use ws sessions search <query> --root cursor=<dir> (or claude, codex, gemini).')
                    roots[client] = Path(directory).expanduser()
            out(core.session_search(a.query, roots)); return 0
        root = core.find_root(a.workspace_root)
        @core.contextlib.contextmanager
        def saved_locally():  # the record is already saved; say so when sharing it cannot go ahead
            try: yield
            except (core.WsError, ValueError, OSError) as exc: raise core.WsError(f'Saved locally, not shared: {exc}') from None
        def share_gate(item, remove=False):
            from . import sharing
            author = getattr(a, 'author', None)
            if author is None: author = sharing.default_author(root)
            from . import team_ui
            plan = sharing.preview(root, item, remove, author, as_format=getattr(a, 'as_format', '')); show(plan, team_ui.share)
            if getattr(a, 'dry_run', False) or plan['unchanged']: return
            if not a.yes:
                print('Apply this exact local team preview? [y/N]')
                if not ask(): return
            out(sharing.apply(root, plan))
        if a.cmd in ('share', 'unshare'):
            share_gate(a.item, a.cmd == 'unshare'); return 0
        if a.cmd == 'scope':
            from . import scope
            out(scope.record(root, a.item, a.value, a.expected_sha)); return 0
        if a.cmd == 'sync':
            from . import team_sync, team_auto
            if a.automatic and not a.pull_only: raise core.WsError('--automatic requires --pull-only.')
            if a.pull_only:
                if a.dry_run: raise core.WsError('--pull-only cannot combine with --dry-run; omit --dry-run for a read-only pull.')
                out(team_auto.pull(root, a.automatic)); return 0
            if a.daily:
                plan = team_auto.schedule(root, a.daily); out(plan)
                if not a.dry_run and plan['supported'] and (a.yes or ask('Activate this exact daily read-only job? [y/N] ')):
                    out(team_auto.schedule(root, a.daily, True, plan))
                return 0
            from . import team_ui
            before = team_ui.entries(root)
            plan = team_sync.preview(root); show(plan, team_ui.sync); published = None
            if not (a.dry_run or not plan['files']) and (a.yes or ask('Publish this exact team sync preview? [y/N] ')):
                out(team_sync.apply(root, plan)); published = list(plan['files'])
            print(team_ui.sync_line(before, team_ui.entries(root), published), file=sys.stderr)  # stderr: stdout stays JSON for scripts
            return 0
        if a.cmd == 'team':
            if a.action == 'status':
                from . import team_status
                if not a.remote and not a.disable_status:
                    rows = team_status.list_entries(root); out(rows)
                    if not rows['entries'] and not rows['warnings']:
                        print('No team status shared. Status sharing is off until someone opts in with ws team status --publish-status (previewed first).', file=sys.stderr)
                    return 0
                plan = team_status.preview(root, a.remote, a.author, a.publish_status, a.disable_status); out(plan)
                if not a.dry_run and (a.yes or ask('Save this exact local status preview? [y/N] ')):
                    out(team_status.apply(root, plan))
                return 0
            if a.action in ('init', 'link') and not a.remote:
                raise core.WsError(f'The remote is missing: run `ws team {a.action} <private-repo>`' + (' (or a folder path with --folder).' if a.folder else '.'))
            if a.folder:
                from . import team_folder
                if a.action not in ('init','link'): raise core.WsError('--folder supports init/link; unlink uses ws team unlink.')
                handler = team_folder.initialize if a.action=='init' else team_folder.link
                from . import team_ui
                plan = handler(root, a.remote, attest=a.attest_private, auto_pull=bool(a.auto_pull))
                if a.dry_run or plan.get('already') or not a.yes: show(plan, team_ui.team)  # with --yes only the result prints
                if not a.dry_run and not plan.get('already') and (a.yes or ask('Link this exact private folder snapshot? [y/N] ')):
                    pulls = a.auto_pull
                    if pulls is None and not a.yes:
                        pulls = ask('Keep team knowledge updated automatically (read-only pulls)? [y/N] ')
                        plan['auto_pull'] = bool(pulls)
                    show(handler(root, a.remote, True, a.attest_private, bool(pulls), plan), team_ui.team_done)
                return 0
            from . import team, team_ui
            plan = team.manage(root, a.action, a.remote, attest=a.attest_private,
                               auto_pull=bool(a.auto_pull), verifier=a.verify_with)
            if a.dry_run or plan.get('already') or not a.yes: show(plan, team_ui.team)  # with --yes only the result prints
            if a.dry_run or plan.get('already'): return 0
            if not a.yes:
                print('Apply this team preview? [y/N]')
                if not ask(): return 0
            pulls = a.auto_pull
            if pulls is None and not a.yes and a.action != 'unlink':
                print('Keep team knowledge updated automatically (pull at session start and daily)? [y/N]')
                pulls = ask()
            show(team.manage(root, a.action, a.remote, True, a.attest_private, bool(pulls), a.verify_with, plan['sha']), team_ui.team_done)
            return 0
        if a.cmd == 'setup':
            from . import setup
            if a.assistants is not None: selected = [name.strip().lower() for name in a.assistants.split(',')]
            elif a.preset:
                selected = json.loads(orchestration.routing_template(a.preset))['assistants']
            elif sys.stdin.isatty():
                detected = [item['assistant'] for item in setup.detect() if item['cli_available'] or item['apps']]
                print('Detected: ' + (', '.join(detected) or 'none') + '. Login/model access is not checked.', file=sys.stderr)
                selected = [name.strip().lower() for name in input('Which assistants do you use? (comma-separated names): ').split(',')]
            else: raise core.WsError('Non-interactive setup needs --assistants a,b or --preset NAME.')
            result = setup.configure(root, selected, a.preset, dry_run=not a.apply)
            out(result); return 2 if result.get('partial') else 0
        if a.cmd == 'route':
            result = orchestration.route(root, a.role)
            out(text_route(result) if a.text or human() else result); return 0 if result['available'] else 2
        if a.cmd == 'worker':
            if a.action == 'launch': out(workers.launch(root, a.id)); return 0
            def confirm(plan):
                print(json.dumps(plan, indent=2), file=sys.stderr)
                print('Apply this worker ' + a.action + ' action? [y/N] ', end='', file=sys.stderr)
                return ask()
            approval = None if a.yes else confirm
            if a.action == 'review': out(workers.review(root, a.id, a.approve, approval))
            elif a.action in ('accept', 'discard'): out(getattr(workers, a.action)(root, a.id, apply=not a.dry_run, confirm=approval))
            else: out(workers.prepare(root, a.task, a.scope, a.base, apply=not a.dry_run, confirm=approval))
            return 0
        if a.cmd == 'delegate':
            if a.selftest:
                if a.task or a.role or a.diff: raise core.WsError('Selftest takes no task, role or diff; run ws delegate --help.')
                binding = orchestration.route(root, 'explorer', a.provider)
                result = orchestration.selftest(root, a.provider, run=binding['provider'] != 'claude' or a.run)
                out(result); return result['exit_code']
            if not a.task or not a.role or a.provider: raise core.WsError('Delegate requires task and --role; --provider is selftest-only.')
            result = orchestration.delegate(root, a.task, a.role, a.run, a.diff); out(result); return 0 if result.get('exit_code', 0) == 0 else 2
        if a.cmd == 'upgrade':
            result = core.upgrade_workspace(root, a.dry_run)
            out(('\n'.join(c['diff'] for c in result['changes']) if a.diff else upgrade.summary(result['changes'])) if result['changes'] else 'No changes.')
            out({'pending_review': result['pending'], 'backups': result['backups']}); return 0
        if a.cmd == 'assist':
            out(assist.apply(root, a.id) if a.action == 'apply' else assist.decide(root, a.id, a.decision, a.until) if a.action == 'decide' else assist.suggestions(root)); return 0
        if a.cmd == 'status':
            result = core.status(root)
            out(text_status(result) if a.text or human() else result)
        elif a.cmd == 'map': out(core.codebase_map(root, a.repo, allow_external=bool(a.repo)))
        elif a.cmd == 'pack':
            from . import packs
            if a.action == 'add' and a.source and not a.name: result = packs.add(root, a.source)
            elif a.action == 'add' and a.name and not a.source: result = core.pack_add(root, a.name)
            elif a.action == 'remove' and a.name and not a.source: result = packs.remove(root, a.name)
            else: raise core.WsError('Use ws pack add <name>, ws pack add --from <dir>, or ws pack remove <name>.')
            collision_notices(result)
            out(result)
        elif a.cmd in ('brief', 'nudge'):
            try: payload = json.load(sys.stdin) if a.hook else {}
            except ValueError: raise core.WsError('Hook input must be a JSON object; stdin was empty or not JSON.')
            branch_task = None
            if not isinstance(payload, dict):
                raise core.WsError('Hook input must be a JSON object.')
            if a.hook and a.cmd == 'brief' and payload.get('hook_event_name') in ('SessionStart', 'sessionStart'):
                from . import team_auto
                update = team_auto.maybe_pull(root)
                if update and update.get('warning'): print(update['warning'], file=sys.stderr)
                try: branch_task = core.session_task(root, payload.get('cwd'))
                except core.WsError: branch_task = None  # a bad cwd must not hide the brief
            if a.hook:
                try: assist.observe(root, payload)
                except OSError: pass  # Optional usage metadata must not block read-only memory.
            if a.hook and a.client != 'claude':
                if a.cmd == 'nudge' and payload.get('hook_event_name') in ('PreCompact', 'Stop', 'preCompact', 'stop', 'sessionEnd', 'PreCompress', 'AfterAgent', 'SessionEnd'):
                    core.capture_decisions(root, payload.get('transcript_path'), a.client,
                                           assist.session_task(root, payload.get('session_id')))
                message, summary = core.brief_and_summary(root, branch_task) if a.cmd == 'brief' else ('', '')
                summary = summary if message and a.client == 'codex' else ''
                out({'additional_context': message} if a.client == 'cursor' and message else
                    {'systemMessage': summary, 'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': message}} if summary else
                    {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': message}} if message else {})
                return 0
            if a.hook and a.cmd == 'nudge' and payload.get('hook_event_name') in ('PreCompact', 'Stop'):
                core.capture_decisions(root, payload.get('transcript_path'), 'claude',
                                       assist.session_task(root, payload.get('session_id')))
            if a.cmd == 'brief' and a.refresh: core.refresh_native(root)
            message, summary = core.brief_and_summary(root, branch_task) if a.cmd == 'brief' else (core.nudge(root), '')
            if a.hook and a.cmd == 'nudge':
                if payload.get('hook_event_name') == 'Stop':
                    uses = claude_tool_uses(payload.get('transcript_path'))
                    idle = uses == []
                    message = message or unrecorded_work(root, uses or [])
                    out({'decision': 'block', 'reason': message} if message and not payload.get('stop_hook_active') and not idle else {})
                elif message:
                    out({'systemMessage': message})
            elif message:
                summary = summary if a.hook and a.cmd == 'brief' and a.client == 'claude' else ''
                out({'systemMessage': summary, 'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': message}} if a.client == 'claude' and summary else message)
        elif a.cmd == 'connect':
            result = core.connect(root, a.client, a.write, skills=a.skills, verify=True)
            if a.client in ('claude', 'codex'):
                location = '.claude/skills' if a.client == 'claude' else '.agents/skills'
                if 'skills' in result:
                    linked = ', '.join(result['skills']['linked']) or 'none'
                    kept = ', '.join(result['skills']['kept']) or 'none'
                    skipped = ', '.join(result['skills']['skipped']) or 'none'
                    print(f"Skills for {a.client}: linked {linked}; kept existing names {kept}; already available in workspace: {skipped}.", file=sys.stderr)
                else:
                    count = core.skills_to_link(a.client, root)
                    if count:
                        print(f"Optional: ws connect {a.client} --skills links {count} extra skill{'s' if count > 1 else ''} into ~/{location}", file=sys.stderr)
                project_skills = Path(root) / location
                if project_skills.is_dir() and any((p / 'SKILL.md').is_file() for p in project_skills.iterdir() if p.is_dir()):
                    print(f'Project skills: available in {location}.', file=sys.stderr)
                print('Restart or reopen the client; approve project MCP/hooks if prompted.', file=sys.stderr)
            if a.client == 'codex':
                if result['connected']:
                    print('Codex MCP config: already configured for this workspace.', file=sys.stderr)
                else:
                    print('Codex MCP config: preview only; not applied. To apply it, run `ws connect codex --write` (an existing config is backed up).', file=sys.stderr)
            out(result['config'] if a.client == 'codex' and not a.write else result)
        elif a.cmd == 'notices':
            out('\n'.join(f"- {n['message']} → {n['suggest']}" for n in core.notices(root)) or 'Nothing to report.')
        elif a.cmd == 'validate':
            res = core.validate(root); out(res); return 0 if res['valid'] else 1
        elif a.cmd == 'task':
            if a.action == 'new': out(core.task_new(root, a.id, a.title, a.objective, a.branch, a.repo))
            elif a.action == 'list': out(core.task_list(root))
            elif a.action == 'find': out(core.task_find(root, a.ref))
            elif a.action == 'depend': out(core.task_depend(root, a.id, a.on))
            elif a.action == 'import':
                res = core.task_import(root, a.file, a.prefix, a.yes); out(res)
                if res['errors']: return 1
            else:
                res = core.task_read(root, a.id, a.section)
                out(res['text'] if 'text' in res else res)
        elif a.cmd == 'next':
            res = core.task_next(root)
            if a.json: out(res)
            else:
                lines = [f"{t['id']} {t['status']} {t['title']}" + (f" (unblocks: {', '.join(t['unblocks'])})" if t['unblocks'] else '')
                         for t in res['ready']] or ['No ready tasks.']
                if res['waiting']: lines.append(f"{res['waiting']} waiting on dependencies")
                out('\n'.join(lines))
        elif a.cmd == 'claim':
            worker = a.worker or os.environ.get('USER') or os.environ.get('USERNAME')
            if not worker:
                raise core.WsError('Set USER (USERNAME on Windows) or pass --worker.')
            out(core.claim(root, a.id, worker))
        elif a.cmd == 'release': out(core.release(root, a.id, a.worker, a.token))
        elif a.cmd == 'checkpoint':
            if (bad := [n for n in a.note if '=' not in n]):
                raise core.WsError(f'--note needs SECTION=TEXT, e.g. --note "Handoff=Decision: use Postgres"; got "{bad[0]}".')
            notes = dict(n.split('=', 1) for n in a.note)
            out(core.checkpoint(root, a.id, a.status, a.next, a.expected_sha, a.worker, a.token, notes))
            if a.status == 'done' and (hint := native.goal_hint(root, a.id)): print(hint, file=sys.stderr)  # stderr keeps stdout JSON clean
        elif a.cmd == 'remember':
            result = core.remember(root, a.text, a.task)
            out(f"Remembered in {result['task']}: {result['remembered']}" if human() else result)
            if a.team:
                from . import sharing
                with saved_locally(): share_gate(sharing.standalone(root, 'decision', a.text))
        elif a.cmd == 'pr-notes':
            result = core.pr_notes(root, a.id, link=not a.no_link)
            print(json.dumps(result, indent=2, ensure_ascii=False) if a.json else result['markdown'], end='' if not a.json else '\n')
        elif a.cmd == 'recap':
            result = core.recap(root, a.since)
            print(json.dumps(result, indent=2, ensure_ascii=False) if a.json else result['markdown'], end='' if not a.json else '\n')
        elif a.cmd == 'know':
            from . import knowledge
            if a.action == 'add':
                item = knowledge.add(root, a.text, a.category, a.team); out({'saved': item})
                if a.team:
                    with saved_locally(): share_gate(item)
            elif a.action == 'list': out(knowledge.list_entries(root, a.category, a.layer))
            else: out(knowledge.show(root, a.id))
        elif a.cmd == 'import': out(native.import_native(root, a.client, a.task, a.yes))
        elif a.cmd == 'search': out(core.search(root, a.query, category=a.category))
        elif a.cmd == 'lesson':
            out(core.lesson_add(root, a.text, a.tag, a.path, a.area) if a.action == 'add' else '\n'.join(core.lesson_search(root, a.query)) or 'No lessons match.')
            if a.action == 'add' and a.team:
                from . import sharing
                with saved_locally(): share_gate(sharing.standalone(root, 'lesson', a.text))
        elif a.cmd == 'feedback':
            if a.action == 'add': out(core.feedback_add(root, a.text, a.kind, a.source))
            elif a.action == 'submit': out(core.feedback_submit(root, a.n, a.yes))
            elif a.action == 'link': out(core.feedback_link(root, a.n, a.url))
            elif a.action == 'sync': out(core.feedback_sync(root))
            else: out([f"{i['n']}. {'[x]' if i['done'] else '[ ]'} {i['kind']}: {i['text']}" + (f" ({i['issue']})" if i['issue'] else '')
                       for i in core.feedback_items(root) if a.all or not i['done']] or 'No open feedback.')
        elif a.cmd == 'digest':
            if a.local_summary and 'local-llm' not in core.config(root).get('packs', []):
                raise core.WsError('Local summary requires the local-llm pack; run `ws pack add local-llm` first.')
            digest = core.digest_file(a.file, focus=a.focus)
            if a.local_summary:
                try:
                    result = subprocess.run([sys.executable, str(core.KIT / 'packs/local-llm/summarize.py'), a.file], env={**os.environ, 'PYTHONUTF8': '1'},  # the child prints UTF-8 too
                                            capture_output=True, encoding='utf-8', errors='replace', timeout=180)
                except (OSError, subprocess.TimeoutExpired) as exc: raise core.WsError(core.redact(f'Local summary failed: {exc}'))
                if result.returncode: raise core.WsError(core.redact(result.stderr.strip()) or 'Local summary failed.')
                digest['local_summary'] = core.redact(result.stdout)
            out(digest)
        elif a.cmd == 'paste':
            if not a.hook:
                if getattr(sys.stdin, 'isatty', lambda: False)():
                    text = core.clipboard_text()
                    if not text: raise core.WsError('Clipboard is empty; copy text before running `ws paste`.')
                else:
                    text = _read_limited_stdin()
                    if not text: raise core.WsError('No input on stdin; run `ws paste` in a terminal to read the clipboard.')
                if len(text.encode('utf-8')) > core.MAX_READ_BYTES:
                    raise core.WsError('Paste exceeds 50 MB; save it to a file and run `ws digest` instead.')
                out(core.paste_save(root, text)['digest'])
            else:
                try: payload = json.loads(_read_limited_stdin())
                except core.WsError as exc:
                    if '50 MB' not in str(exc): out({}); return 0  # unreadable input: allow the prompt rather than block every one
                    return _block_prompt(a.client, 'Prompt hook input exceeds 50 MB. Save the source as a file and run `ws digest <file> --focus "<pattern>"` instead.')
                except json.JSONDecodeError:
                    out({}); return 0
                if not isinstance(payload, dict) or not isinstance(payload.get('prompt'), str):
                    out({}); return 0
                prompt = payload.get('prompt', '')
                lines = prompt.splitlines() if isinstance(prompt, str) else []
                if not core.prompt_is_large(prompt) or lines and lines[0].strip() == '!raw':
                    out({}); return 0
                try:
                    path = core.paste_save(root, prompt)['path'].relative_to(root).as_posix()
                    reason = (f'Prompt saved, redacted, to {path}. Send a short question plus the relevant excerpt, '
                              f'or run `ws digest {path} --focus "<pattern>"`; put !raw alone on the first line to bypass.')
                except (core.WsError, OSError, UnicodeError):
                    reason = ('Prompt is too large to save in .ws/inbox/. Send a short question plus the relevant excerpt, '
                              'or save the source as a file and run `ws digest <file> --focus "<pattern>"`; '
                              'put !raw alone on the first line to bypass.')
                return _block_prompt(a.client, reason)
        elif a.cmd == 'trace': out(core.trace(root, a.task))
        elif a.cmd == 'run':
            if a.action == 'import': out(core.import_codeburn(root, a.since, a.task)); return 0
            if a.action == 'log':
                out(core.run_log(root, a.task, a.step, a.provider, a.model, a.tokens_in, a.tokens_out, a.seconds, a.result, a.note,
                                 a.worker_role, a.effort, a.check, a.files, a.verdict, a.findings))
            else: out(core.run_report(root, a.task))
        return 0
    except Exception as exc:
        if a.cmd in ('guard', 'discipline') or getattr(a, 'hook', False) and a.cmd in ('brief', 'nudge', 'paste'):
            print(f'ws: hook skipped ({type(exc).__name__}: {str(exc)[:200]})', file=sys.stderr)  # fail open: exit 2 would block the client
            print('{}'); return 0
        if not isinstance(exc, (core.WsError, FileNotFoundError, json.JSONDecodeError)): raise
        message = str(exc)
        if isinstance(exc, core.WsError) and not any(hint in message.lower() for hint in ('`ws ', 'run ws ', 'see ws ', 'next:')):
            message += ('' if message.endswith(('.', '!', '?', ':')) else '.') + f' Next: run `ws {a.cmd} --help`.'
        print(f'ws: {message}', file=sys.stderr)
        if not isinstance(exc, core.WsError):
            print('If this looks like a bug in ws, record it: ws feedback add "<what you ran and saw>" --kind bug', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
