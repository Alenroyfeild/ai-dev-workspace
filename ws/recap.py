"""Read-only recaps; local task history never broadens team sharing."""
import datetime
import json
import re
from . import core


def record(text, event):
    event = dict(event)
    if event.get('kind') == 'decision': event['text'] = _clean(event['text'])
    row = json.dumps(dict(at=core.now(), **event), ensure_ascii=False)
    return core.set_section(text, 'Activity', '\n'.join(filter(None, (core.section(text, 'Activity'), row))))


def _date(value):
    if not isinstance(value, str) or len(value) > 40: raise ValueError('Invalid date')
    stamp = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None: raise ValueError('Date needs a timezone')
    return stamp


def _clean(text):
    if re.search(r'#private\b', text, re.I) or text.lstrip().lower().startswith('/private'): return ''
    return ' '.join(core.redact(core.PRIVATE_RE.sub('', text)).split())[:500]


def report(root, since='7d'):
    if not re.fullmatch(r'[1-9][0-9]{0,3}d', since) or int(since[:-1]) > 3650:
        raise core.WsError('Use --since <1..3650>d, for example --since 7d.')
    end = _date(core.now()); start = end - datetime.timedelta(days=int(since[:-1]))
    tasks = []; teammates = []; warnings = []
    for task in core.task_list(root):
        try:
            data = core.task_read(root, task['id'], ['Activity', 'Handoff', 'Next action'])
            updated = data['meta'].get('updated', data['meta'].get('created', ''))
            updated = _date(updated + 'T00:00:00+00:00' if re.fullmatch(r'\d{4}-\d\d-\d\d', updated) else updated)
            lines = data['sections']['Activity'].splitlines(); events = []
            if len(lines) > 1000: warnings.append(task['id'] + ': only the last 1000 activity entries examined.')
            for line in lines[-1000:]:
                try:
                    if len(line) > 4096: raise ValueError('Oversized event')
                    event = json.loads(line); stamp = _date(event['at'])
                    kind = event['kind']
                    if kind == 'status':
                        if event['from'] not in core.STATUSES or event['to'] not in core.STATUSES: raise ValueError('Invalid status')
                        row = dict(at=event['at'], kind=kind, **{'from': event['from'], 'to': event['to']})
                    elif kind == 'decision' and isinstance(event['text'], str):
                        row = dict(at=event['at'], kind=kind, text=_clean(event['text']))
                    else: raise ValueError('Unknown event')
                    if start <= stamp <= end: events.append(row)
                except (ValueError, KeyError, TypeError, RecursionError): warnings.append(task['id'] + ': invalid activity entry excluded.')
            if not events and not start <= updated <= end: continue
            handoff = re.sub(r'<!-- ws:captured:.*?<!-- /ws:captured -->', '', data['sections']['Handoff'], flags=re.S)
            decisions = list(filter(None, (_clean(line[10:]) for line in handoff.splitlines() if line.startswith('Decision: '))))
            if len(decisions) > 5: warnings.append(task['id'] + ': only the last five current decisions shown.')
            tasks.append(dict(id=task['id'], title=_clean(task['title']), status=task['status'],
                              events=events, current_decisions=[d for d in decisions[-5:] if d]))
        except (core.WsError, OSError, ValueError): warnings.append(task['id'] + ': unreadable task excluded.')
    if core.config(root).get('team_workspace'):
        from . import knowledge, team_status
        try:
            entries = knowledge.list_entries(root, layer='team', _all=True); warnings += entries['warnings']
            for row in entries['entries']:
                kind = row['source'].partition(':')[0]
                if kind not in ('decision', 'task'): continue
                try: stamp = _date(row['date'])
                except ValueError: warnings.append('Team snapshot with invalid date excluded.'); continue
                if start <= stamp <= end:
                    teammates.append(dict(author=row['author'], task=row['source'], at=row['date'],
                                          kind=kind + ' snapshot', text=_clean(row['summary']), untrusted=True))
            statuses = team_status.list_entries(root); warnings += statuses['warnings']
            for row in statuses['entries']:
                if start <= _date(row['date']) <= end:
                    teammates.append(dict(author=row['author'], task=row['task'], at=row['date'],
                                          kind='status snapshot', text=row['line'], untrusted=True))
        except (core.WsError, OSError, ValueError): warnings.append('Team snapshots unavailable; private recap retained.')
    return dict(since=start.isoformat(), tasks=tasks, team=teammates, warnings=sorted(set(warnings)))


def render(result):
    lines = ['Recap since ' + result['since']]
    for task in result['tasks']:
        lines.append(f"{task['id']} — {task['title']} (current snapshot: {task['status']})")
        for event in task['events']:
            text = event['text'] if event['kind'] == 'decision' else event['from'] + ' → ' + event['to']
            lines.append('  ' + event['at'] + ' ' + event['kind'] + ': ' + text)
        recorded = {e.get('text') for e in task['events'] if e['kind'] == 'decision'}
        lines += ['  Current decision snapshot (date not shown): ' + d for d in task['current_decisions'] if d not in recorded]
    for row in result['team']:
        lines.append(f"Team (untrusted) {row['author']} / {row['task']} — {row['at']} {row['kind']}: {row['text']}")
    lines += ['Warning: ' + warning for warning in result['warnings']]
    if not result['tasks'] and not result['team']: lines.append('No recorded activity in this period.')
    return '\n'.join(lines)
