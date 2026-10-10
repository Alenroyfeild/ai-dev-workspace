"""`ws` command line. Every command prints JSON or plain text and exits non-zero on error."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import core, assist, orchestration, native


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


COMMAND_GROUPS = (
    ('Setup', ('init', 'connect', 'packs', 'pack')),
    ('Daily', ('status', 'task', 'next', 'claim', 'release', 'checkpoint', 'brief', 'nudge', 'paste', 'search', 'sessions', 'import', 'lesson')),
    ('Orchestration', ('route', 'delegate')),
    ('Measure', ('tools', 'digest', 'run', 'trace')),
    ('Maintain', ('doctor', 'validate', 'map', 'feedback', 'update', 'version', 'upgrade', 'notices', 'assist')),
)


class GroupedHelpFormatter(argparse.HelpFormatter):
    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction) and action.dest == 'cmd':
            choices = {item.dest: item for item in action._choices_actions}
            output = []
            for label, commands in COMMAND_GROUPS:
                output.append(' ' * self._current_indent + label + ':\n')
                self._indent()
                output.extend(argparse.HelpFormatter._format_action(self, choices[name])
                              for name in commands if name in choices)
                self._dedent()
            extra = choices.keys() - {name for _, commands in COMMAND_GROUPS for name in commands}
            if extra:
                output.append(' ' * self._current_indent + 'Other:\n')
                self._indent()
                output.extend(argparse.HelpFormatter._format_action(self, choices[name]) for name in sorted(extra))
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
    clients = report.get('configured_clients', {})
    if clients:
        lines.append('Configured clients: ' + (', '.join(name for name, configured in clients.items() if configured) or 'none'))
    goals = report.get('codex_goals')
    if goals:
        lines.append(f"Codex goals: {goals['active']} active, {goals['complete']} complete" if 'active' in goals
                     else f"Codex goals: skipped ({goals['skipped']})")
    lines.extend(f'Conflicted: {hint}' for hint in report.get('conflicted', []))
    lines.extend(f'Team: {warning}' for warning in report.get('team', {}).get('warnings', []))
    health = report.get('capture_health')
    if health:
        lines.append(f"Last capture outcome: {health.get('outcome', 'unknown')} "
                     f"({health.get('client', 'unknown')}, {health.get('date', 'unknown')}; {health.get('reason', 'unknown')})")
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
        transcript = path.open(encoding='utf-8')
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
                except (KeyError, TypeError, json.JSONDecodeError):
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


def main(argv=None):
    p = argparse.ArgumentParser(prog='ws', description='AI Dev Workspace: shared memory and coordination for AI-assisted development.',
                                formatter_class=GroupedHelpFormatter)
    p.add_argument('--workspace-root', help='explicit workspace directory (also used by generated hooks)')
    sub = p.add_subparsers(dest='cmd', required=True, title='Commands', metavar='COMMAND')

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
    sub.add_parser('validate', help='check task records, links and secrets')
    s = sub.add_parser('doctor', help='check which tools are installed'); s.add_argument('--mcp', action='store_true', help='run project MCP connection checks'); s.add_argument('--text', action='store_true', help='show a human-readable summary')
    s = sub.add_parser('map', help='write a compact codebase map'); s.add_argument('repo', nargs='?')
    s = sub.add_parser('connect', help='connect an assistant to this workspace')
    s.add_argument('client', choices=('claude', 'codex', 'cursor', 'vscode', 'gemini'))
    s.add_argument('--write', action='store_true', help='append Codex global config with a backup')

    t = sub.add_parser('task', help='task records').add_subparsers(dest='action', required=True)
    s = t.add_parser('new'); s.add_argument('id'); s.add_argument('title')
    s.add_argument('--objective', default=''); s.add_argument('--branch', default=''); s.add_argument('--repo', default='')
    t.add_parser('list')
    s = t.add_parser('find'); s.add_argument('ref')
    s = t.add_parser('show'); s.add_argument('id'); s.add_argument('--section', action='append')
    s = t.add_parser('depend', help='make a task wait for another'); s.add_argument('id'); s.add_argument('--on', required=True, metavar='OTHER')
    s = t.add_parser('import', help='create tasks from Task Master tasks.json or a Spec Kit tasks.md (preview unless --yes)')
    s.add_argument('file'); s.add_argument('--prefix', default='SPEC'); s.add_argument('--yes', action='store_true', help='write the tasks')
    s = sub.add_parser('next', help='open tasks whose dependencies are done'); s.add_argument('--json', action='store_true')

    s = sub.add_parser('claim', help='claim a task'); s.add_argument('id'); s.add_argument('--worker')
    s = sub.add_parser('release', help='release a task claim'); s.add_argument('id'); s.add_argument('--worker'); s.add_argument('--token')
    s = sub.add_parser('checkpoint', help='save task status and next action'); s.add_argument('id'); s.add_argument('--status', required=True, choices=core.STATUSES)
    s.add_argument('--next', required=True); s.add_argument('--expected-sha'); s.add_argument('--worker'); s.add_argument('--token')
    s.add_argument('--note', action='append', default=[], metavar='SECTION=TEXT')

    s = sub.add_parser('search', help='ranked vault search (snippets, not whole files)'); s.add_argument('query')
    sessions = sub.add_parser('sessions', help='search local assistant transcripts').add_subparsers(dest='action', required=True)
    s = sessions.add_parser('search'); s.add_argument('query')
    s.add_argument('--root', action='append', metavar='CLIENT=DIR', help='search explicit transcript directories instead of defaults')
    s = sub.add_parser('import', help='preview or import assistant-native memories (read-only)').add_subparsers(dest='action', required=True).add_parser('native')
    s.add_argument('--client', choices=(*native.CLIENTS, 'all'), default='all'); s.add_argument('--task'); s.add_argument('--yes', action='store_true')
    l = sub.add_parser('lesson', help='add or search reusable lessons').add_subparsers(dest='action', required=True)
    s = l.add_parser('add'); s.add_argument('text'); s.add_argument('--tag', action='append', default=[])
    s.add_argument('--path', action='append', default=[], help='relative repo glob; repeat for multiple paths'); s.add_argument('--area', default='')
    s = l.add_parser('search'); s.add_argument('query', nargs='?', default='')
    f = sub.add_parser('feedback', help='record or submit product feedback').add_subparsers(dest='action', required=True)
    s = f.add_parser('add'); s.add_argument('text'); s.add_argument('--kind', default='idea'); s.add_argument('--source', default='user')
    s = f.add_parser('list'); s.add_argument('--all', action='store_true')
    s = f.add_parser('submit', help='turn item N into a GitHub issue (preview first)'); s.add_argument('n', type=int); s.add_argument('--yes', action='store_true')
    s = f.add_parser('link', help='record the issue URL for item N'); s.add_argument('n', type=int); s.add_argument('url')
    f.add_parser('sync', help='tick items whose issue is closed')
    s = sub.add_parser('update', help='check for or install a new kit release'); s.add_argument('--check', action='store_true')
    sub.add_parser('version')
    s = sub.add_parser('upgrade', help='preview or apply managed workspace updates'); s.add_argument('--dry-run', action='store_true')
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

    a = p.parse_args(argv)
    try:
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
        if a.cmd == 'route':
            result = orchestration.route(root, a.role)
            out(text_route(result) if a.text or human() else result); return 0 if result['available'] else 2
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
            out('\n'.join(c['diff'] for c in result['changes']) or 'No changes.')
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
            payload = json.load(sys.stdin) if a.hook else {}
            if not isinstance(payload, dict):
                raise core.WsError('Hook input must be a JSON object.')
            if a.hook: assist.observe(root, payload)
            if a.hook and a.client != 'claude':
                if a.cmd == 'nudge' and payload.get('hook_event_name') in ('PreCompact', 'Stop', 'preCompact', 'stop', 'sessionEnd', 'PreCompress', 'AfterAgent', 'SessionEnd'):
                    core.capture_decisions(root, payload.get('transcript_path'), a.client)
                message = core.brief(root) if a.cmd == 'brief' else ''
                out({'additional_context': message} if a.client == 'cursor' and message else
                    {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': message}} if message else {})
                return 0
            if a.hook and a.cmd == 'nudge' and payload.get('hook_event_name') in ('PreCompact', 'Stop'):
                core.capture_decisions(root, payload.get('transcript_path'))
            if a.cmd == 'brief' and a.refresh: core.refresh_native(root)
            message = core.brief(root) if a.cmd == 'brief' else core.nudge(root)
            if a.hook and a.cmd == 'nudge':
                if payload.get('hook_event_name') == 'Stop':
                    uses = claude_tool_uses(payload.get('transcript_path'))
                    idle = uses == []
                    message = message or unrecorded_work(root, uses or [])
                    out({'decision': 'block', 'reason': message} if message and not payload.get('stop_hook_active') and not idle else {})
                elif message:
                    out({'systemMessage': message})
            elif message:
                out(message)
        elif a.cmd == 'connect':
            result = core.connect(root, a.client, a.write, skills=True, verify=True)
            if 'skills' in result:
                linked = ', '.join(result['skills']['linked']) or 'none'
                kept = ', '.join(result['skills']['kept']) or 'none'
                skipped = ', '.join(result['skills']['skipped']) or 'none'
                print(f"Skills for {a.client}: linked {linked}; kept existing names {kept}; already available in workspace: {skipped}.", file=sys.stderr)
                location = '.claude/skills' if a.client == 'claude' else '.agents/skills'
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
            worker = a.worker or os.environ.get('USER')
            if not worker:
                raise core.WsError('Set USER or pass --worker.')
            out(core.claim(root, a.id, worker))
        elif a.cmd == 'release': out(core.release(root, a.id, a.worker, a.token))
        elif a.cmd == 'checkpoint':
            notes = dict(n.split('=', 1) for n in a.note)
            out(core.checkpoint(root, a.id, a.status, a.next, a.expected_sha, a.worker, a.token, notes))
            if a.status == 'done' and (hint := native.goal_hint(root, a.id)): print(hint, file=sys.stderr)  # stderr keeps stdout JSON clean
        elif a.cmd == 'import': out(native.import_native(root, a.client, a.task, a.yes))
        elif a.cmd == 'search': out(core.search(root, a.query))
        elif a.cmd == 'lesson':
            out(core.lesson_add(root, a.text, a.tag, a.path, a.area) if a.action == 'add' else '\n'.join(core.lesson_search(root, a.query)) or 'No lessons match.')
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
                    result = subprocess.run([sys.executable, str(core.KIT / 'packs/local-llm/summarize.py'), a.file],
                                            capture_output=True, text=True, timeout=180)
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
                    if '50 MB' not in str(exc):
                        return _block_prompt(a.client, 'This client prompt-hook input is not valid UTF-8. Retry with a short question plus the relevant excerpt.')
                    return _block_prompt(a.client, 'Prompt hook input exceeds 50 MB. Save the source as a file and run `ws digest <file> --focus "<pattern>"` instead.')
                except json.JSONDecodeError:
                    return _block_prompt(a.client, 'This client sent malformed prompt-hook data. Retry with a short question plus the relevant excerpt.')
                if not isinstance(payload, dict) or not isinstance(payload.get('prompt'), str):
                    return _block_prompt(a.client, 'This client did not provide a valid prompt. Retry with a short question plus the relevant excerpt.')
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
    except (core.WsError, FileNotFoundError, json.JSONDecodeError) as exc:
        message = str(exc)
        if isinstance(exc, core.WsError) and not any(hint in message.lower() for hint in ('`ws ', 'run ws ', 'see ws ', 'next:')):
            message += ' Next: run `ws --help` for the relevant command.'
        print(f'ws: {message}', file=sys.stderr)
        if not isinstance(exc, core.WsError):
            print('If this looks like a bug in ws, record it: ws feedback add "<what you ran and saw>" --kind bug', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
