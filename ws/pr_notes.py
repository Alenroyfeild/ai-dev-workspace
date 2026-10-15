"""Print a reviewable PR-description draft from saved task text."""
import re

from . import core, sharing


def render(root, task_id=None):
    task_id = task_id or core.sole_local_claim(root)
    if not task_id:
        raise core.WsError('Choose a task: ws pr-notes <ID>, or ws claim <ID>.')
    record = core.task_read(root, task_id)
    if record.get('conflicted'):
        raise core.WsError(core.conflict_hint(task_id))
    text = re.sub(r'<!-- ws:captured:.*?<!-- /ws:captured -->', '', record['text'], flags=re.S)
    text = sharing.portable(root, text)
    title = re.search(r'^# (.+)$', text, re.M)
    handoff = core.section(text, 'Handoff')
    decisions = '\n'.join(line for line in handoff.splitlines()
                          if re.match(r'\s*(?:[-*]\s*)?(?:Decision|Reason):', line, re.I))
    fields = [('Objective', core.section(text, 'Objective')), ('Decisions and reasons', decisions),
              ('Checks (recorded, not rerun)', core.section(text, 'Checks'))]
    source = core.task_path(root, task_id).relative_to(root).as_posix()
    return (f'## Task: {task_id} — {title.group(1) if title else task_id}\n\n'
            f'Source: `{source}` (saved task record; review before publishing).\n\n' +
            '\n\n'.join('### ' + label + '\n' + (body or 'Not recorded.') for label, body in fields))
