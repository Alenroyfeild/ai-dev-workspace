"""Local suggestions and explicit permission; never install or edit client config."""
import datetime
import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from . import core


def state(root):
    path = root / '.ws/assist.json'
    return json.loads(path.read_text()) if path.exists() else {}


def save(root, data):
    core.atomic_write(root / '.ws/assist.json', json.dumps(data) + '\n')


def cost_data():
    if not core.shutil.which('codeburn'):
        return {}, {}
    # notices runs at every session start: reuse one Codeburn scan per day instead of ~30 s of subprocesses.
    cache = Path.home() / '.cache' / 'ai-dev-workspace' / 'codeburn-assist.json'
    try:
        cached = json.loads(cache.read_text())
        if cached.get('day') == core.now()[:10]:
            return cached['report'], cached['usage']
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    report, usage = _scan()
    if report or usage:
        cache.parent.mkdir(parents=True, exist_ok=True)
        core.atomic_write(cache, json.dumps({'day': core.now()[:10], 'report': report, 'usage': usage}))
    return report, usage


def _scan():
    try:
        report = subprocess.run(['codeburn', 'optimize', '--format', 'json'], capture_output=True, text=True, timeout=15)
        since = (datetime.date.fromisoformat(core.now()[:10]) - datetime.timedelta(days=30)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'usage.json'
            export = subprocess.run(['codeburn', 'export', '-f', 'json', '-o', str(path), '--from', since], capture_output=True, text=True, timeout=15)
            return json.loads(report.stdout), json.loads(path.read_text()) if export.returncode == 0 else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}, {}


def observe(root, payload):
    if not payload.get('session_id') and not payload.get('transcript_path'):
        return
    with core.lock(root):
        data = state(root)
        if payload.get('hook_event_name') in ('SessionStart', 'sessionStart') and payload.get('session_id'):
            data.pop('long_session_bytes', None)
            for task in core.task_list(root):
                if not task['claimed_by']:
                    continue
                meta = core.task_read(root, task['id'], ['Next action'])['meta']
                count = meta.get('checkpoint_count', '0')
                record = data.setdefault('sessions', {}).setdefault(task['id'], {})
                sid = core.digest_text(str(payload['session_id']))
                if record.get('last') != sid:
                    record.update(last=sid, count=(record.get('count', 0) if record.get('checkpoint') == count else 0) + 1, checkpoint=count)
        try:
            size = Path(payload.get('transcript_path', '')).stat().st_size
            if size > 2000000:
                data['long_session_bytes'] = size
        except OSError:
            pass
        save(root, data)


def feature_suggestions(root, add):
    cfg = core.config(root)
    pending = cfg.get('upgrade_pending') or any(p.is_file() for p in root.rglob('*.ws-new*'))
    if core._vtuple(core.kit_meta()['version']) > core._vtuple(cfg.get('kit_version', '0')) or pending:
        add('upgrade', 'Kit is newer than this workspace or .ws-new proposals await review', 'ws upgrade --dry-run', 'local-reversible')
    from . import orchestration
    path = root / '.ws/delegate-selftests.json'
    try: records = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError): records = {}
    if not isinstance(records, dict): records = {}
    seen = set()
    for role in ('worker', 'explorer', 'reviewer'):
        try: binding = orchestration.route(root, role)
        except core.WsError: continue
        provider = binding.get('provider')
        record = records.get(provider, {})
        if (binding.get('available') and provider in ('codex', 'claude') and provider not in seen
                and core._detected(provider) and not (isinstance(record, dict) and record.get('executed'))):
            add('selftest-' + provider, 'Routed read-only provider has no executed selftest: ' + provider,
                'ws delegate --selftest --provider ' + provider, 'paid-run' if provider == 'codex' else 'local-reversible')
        seen.add(provider)
    for client, checks in (('cursor', ['cursor', 'app:Cursor']), ('vscode', ['code', 'app:Visual Studio Code']), ('gemini', ['gemini'])):
        if core._detected(checks) and not core.client_connected(root, client):
            add('connect-' + client, 'Installed client has no matching workspace connection: ' + client, 'ws connect ' + client, 'changes-config')


def suggestions(root, include_hidden=False):
    data, items = state(root), []
    def add(identifier, why, command, safety, saving='unmeasured'):
        items.append(dict(id=identifier, why=' '.join(core.redact(why).split()), command=command, safety=safety, estimated_saving=saving))
    feature_suggestions(root, add)
    for tool in core.tools():
        if tool['level'] == 'recommended' and not tool['installed'] and core.tool_policy(root, tool)['mode'] != 'off':
            add('tool-' + tool['name'], 'Recommended executable missing: ' + tool['name'], tool['install']['codex'], 'installs')
    repos = core.config(root).get('repos', [])
    mapped = core.vault(root) / 'Project/Codebase map.md'
    if repos and (not mapped.exists() or core.time.time() - mapped.stat().st_mtime > 14 * 86400):
        add('map', 'Configured repository map missing or older than 14 days', 'ws map ' + shlex.quote(repos[0]), 'local-reversible')
    if repos and core.shutil.which('graphify') and not (Path(repos[0]) / 'graphify-out').exists():
        add('graph', 'Graphify installed; configured repository has no graphify-out directory', 'graphify ' + shlex.quote(repos[0]), 'external')
    tasks = core.task_list(root)
    if not core.lesson_search(root, '') and sum(int(core.task_read(root, t['id'], ['Next action'])['meta'].get('checkpoint_count', 0)) for t in tasks) >= 5:
        add('lesson', 'No lessons after at least 5 recorded checkpoints', 'ws lesson add "<what happened → rule>"', 'local-reversible')
    for task in tasks:
        record = data.get('sessions', {}).get(task['id'], {})
        count = core.task_read(root, task['id'], ['Next action'])['meta'].get('checkpoint_count', '0')
        if task['claimed_by'] and record.get('checkpoint') == count and record.get('count', 0) >= 3:
            add('checkpoint-' + task['id'], 'Claim has spanned 3 sessions without a new checkpoint: ' + task['id'], '/handoff (Claude) or $handoff (Codex)', 'local-reversible')
    if data.get('long_session_bytes'):
        add('long-session', f"Transcript exceeded 2000000 bytes ({data['long_session_bytes']}); start fresh after handoff", '/handoff (Claude) or $handoff (Codex)', 'local-reversible')
    guard = core.repeat_guard(root)
    if guard:
        add('trace', guard, 'ws trace ' + guard.split()[1].rstrip(':'), 'local-reversible')
        items.insert(0, items.pop())
    report, usage = cost_data()
    used = [row['Server'].lower() for row in usage.get('mcp', []) if row.get('Calls', 0) > 0]
    pinned = [name.lower() for name, value in core.config(root).get('tool_overrides', {}).items() if value == 'on']
    for finding in report.get('findings', []):
        text = json.dumps(finding).lower()
        if any(name in text for name in ['ccd_', 'claude-in-chrome', 'ai-dev-workspace', 'workspace', 'graphy', 'graphif', *used, *pinned]):
            continue
        if 'mcp' in text and 'mcp' not in usage:
            continue  # Missing usage evidence: fail closed for connector advice.
        if finding.get('class') == 'keep':
            continue
        identifier = str(finding.get('id', ''))
        if re.fullmatch(r'[a-zA-Z0-9_-]+', identifier):
            add('cost-' + identifier, 'Review Codeburn: ' + finding.get('title', '') + '; ' + finding.get('explanation', '')[:180],
                'codeburn optimize --format json', 'changes-config', f"up to ${finding.get('estimatedSavingsUSD', 0):.2f} in the scanned period (estimate)")
    today = core.now()[:10]
    return [item for item in items if include_hidden or data.get('permissions', {}).get(item['id'], {}).get('until', '') <= today][:2 if not include_hidden else len(items)]


def decide(root, identifier, decision, until=None):
    items = {item['id']: item for item in suggestions(root, True)}
    if identifier not in items or decision not in ('accepted', 'declined', 'snoozed', 'always'):
        raise core.WsError('Choose a current suggestion and accepted, declined, snoozed or always.')
    if decision == 'always' and identifier not in ('map', 'trace'):
        raise core.WsError('Always is allowed only for map and trace, never installs or configuration changes.')
    if decision == 'snoozed':
        try: datetime.date.fromisoformat(until or '')
        except ValueError: raise core.WsError('Snoozed requires --until YYYY-MM-DD.')
    if decision == 'declined':
        until = (datetime.date.fromisoformat(core.now()[:10]) + datetime.timedelta(days=30)).isoformat()
    with core.lock(root):
        data = state(root); data.setdefault('permissions', {})[identifier] = dict(decision=decision, until=until or '')
        save(root, data)
    return {'id': identifier, 'decision': decision, 'until': until}


def apply(root, identifier):
    permission = state(root).get('permissions', {}).get(identifier, {}).get('decision')
    items = {item['id']: item for item in suggestions(root, True)}
    if identifier not in items or identifier not in ('map', 'trace') or permission not in ('accepted', 'always'):
        raise core.WsError('Accept a current map/trace suggestion first; run other commands yourself after review.')
    return core.codebase_map(root) if identifier == 'map' else core.trace(root, items['trace']['command'].split()[-1])


def notices(root, limit, existing=()):
    candidates = [dict(id='notice-' + core.digest_text(json.dumps(item)), notice=item) for item in existing] + suggestions(root, True)
    with core.lock(root):
        data = state(root); seen = data.get('offered', [])
        items = [item for item in candidates if item['id'] not in seen and data.get('permissions', {}).get(item['id'], {}).get('until', '') <= core.now()[:10]][:limit]
        data['offered'] = seen + [item['id'] for item in items]; save(root, data)
    return [item['notice'] if 'notice' in item else dict(kind='toolbox' if item['id'].startswith('tool-') else 'assist', tool=item['id'].removeprefix('tool-'),
                 message=item['why'] + ' Ask before applying.', suggest=item['command']) for item in items]
