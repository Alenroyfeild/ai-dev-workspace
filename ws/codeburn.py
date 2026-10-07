"""Import local Codeburn v2 accounting records without storing private paths."""
import datetime
import json
import tempfile
from pathlib import Path
from . import core


def timestamp(value):
    stamp = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return stamp.replace(tzinfo=datetime.timezone.utc) if stamp.tzinfo is None else stamp


def import_usage(root, since=None, task_id=None):
    try:
        minimum = timestamp(since) if since else None
        if since: datetime.date.fromisoformat(since)
    except (ValueError, TypeError):
        raise core.WsError('Since must be YYYY-MM-DD.')
    if not core.shutil.which('codeburn'):
        raise core.WsError('Codeburn missing. Install it yourself: npm install -g codeburn')
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'usage.json'
            command = ['codeburn', 'export', '-f', 'json', '-o', str(path)]
            if since: command += ['--from', since]
            result = core.subprocess.run(command, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise core.WsError('Codeburn export failed; diagnose locally with codeburn export -f json -o <temporary path>.')
            data = json.loads(path.read_text())
    except (OSError, ValueError, core.subprocess.TimeoutExpired) as exc:
        raise core.WsError('Codeburn export unavailable or invalid; no usage imported.') from exc
    if not isinstance(data, dict) or data.get('schema') != 'codeburn.export.v2' or not isinstance(data.get('records'), list):
        raise core.WsError('Expected codeburn.export.v2 with accounting records.')
    selected = [task_id] if task_id else [task['id'] for task in core.task_list(root)]
    windows = []
    for identifier in selected:
        meta = core.task_read(root, identifier, ['Next action'])['meta']
        projects = [meta['repo']] if meta.get('repo') else [str(root), *core.config(root).get('repos', [])]
        start = timestamp(meta.get('claimed_at') or meta['created'])
        end = timestamp(meta.get('checkpoint_at') or meta.get('updated') or core.now()) if meta.get('status') == 'done' else timestamp(core.now())
        if meta.get('status') == 'done' and len(meta.get('updated', '')) == 10 and not meta.get('checkpoint_at'):
            end += datetime.timedelta(days=1)
        windows.append((identifier, {str(Path(p).expanduser().resolve()) for p in projects}, start, end))
    pending, ambiguous = [], 0
    for row in data['records']:
        try:
            if not isinstance(row, dict): raise ValueError()
            counts = [row.get(k, 0) for k in ('inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens')]
            if any(type(n) is not int or n < 0 for n in counts): raise ValueError()
            at = timestamp(row['timestamp']); project = str(Path(row['project']).expanduser().resolve())
            provider = core.redacted_line(row['provider'], 'Provider')
            model = core.redacted_line(row.get('model', ''), 'Model')
            if not isinstance(row['sessionId'], str) or not provider: raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            raise core.WsError('Invalid Codeburn record; no usage imported.')
        if minimum and at < minimum: continue
        matches = [identifier for identifier, paths, start, end in windows if project in paths and start <= at <= end]
        if len(matches) > 1:
            ambiguous += 1; continue
        if not matches: continue
        pending.append((matches[0], provider, model, counts[0] + counts[2] + counts[3], counts[1], row['timestamp'],
                        (project, row['sessionId'])))
    # One run entry per task, session, provider and model: per-call rows would bury ws trace in thousands of lines.
    sessions = {}
    for identifier, provider, model, incoming, outgoing, at, session in pending:
        group = sessions.setdefault((identifier, provider, model, session), [0, 0, at])
        group[0] += incoming; group[1] += outgoing; group[2] = max(group[2], at)
    pending = [(identifier, provider, model, incoming, outgoing, at,
                core.digest_text(json.dumps([*session, provider, model, incoming, outgoing, at])))
               for (identifier, provider, model, session), (incoming, outgoing, at) in sessions.items()]
    imported = 0
    for identifier, provider, model, incoming, outgoing, at, key in pending:
        entry = core.run_log(root, identifier, 'Codeburn usage', provider, model, incoming, outgoing,
                             result='skipped', note='Measured telemetry; input includes cache read/write. Not a review verdict.',
                             source='codeburn', import_id=key, at=at)
        imported += entry is not None
    return {'imported': imported, 'ambiguous': ambiguous, 'unmatched': len(data['records']) - len(pending) - ambiguous}
