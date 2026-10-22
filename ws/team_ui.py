"""Short human summaries of team previews; scripts and non-terminals keep the full JSON plans."""
import json
import re
from . import core, sharing

ENTRY = re.compile(r'entries/[a-f0-9]{32}\.md')


def _one(text):
    return ' '.join(text.split())[:70]


def _full(text):
    """Everything being published must be visible at consent; only very long notes are cut."""
    text = ' '.join(text.split())
    return text if len(text) <= 600 else text[:600] + f'\u2026 ({len(text) - 600} more characters; WS_JSON=1 shows all)'


def where(plan):
    folder = plan.get('host') == 'folder' or 'source' in plan
    return ('shared folder ' if folder else 'private repo ') + str(plan.get('remote') or plan.get('source') or '')


def share(plan):
    if plan['unchanged']: return 'Nothing to change: this note is already shared as written.'
    sign = '-' if plan['unshare'] else '+'
    return '\n'.join([f"{'Will remove from' if plan['unshare'] else 'Will share with'} your team ({where(plan)}):",
                      f"{sign} {plan['category']} {(_one if plan['unshare'] else _full)(plan['text'])}".rstrip(),
                      f"  by {plan['author']}, file {plan['destination']}",
                      'Check the line above for anything private. Nothing is pushed until ws sync.'])


def _file(name, text):
    if ENTRY.fullmatch(name):
        category, body = sharing.entry_parts(text) if text is not None else ('', '')
        return f'+ {category} {_full(body)}'.rstrip() if text is not None else f'- {name} (removed)'
    if name.startswith('status/'):
        try: row = json.loads(text)
        except (TypeError, ValueError): row = {}
        return f"+ status {row.get('author', name)}: {_one(str(row.get('line', '')))}" if text is not None else f'- {name} (removed)'
    if name == 'team.json': return '+ team manifest (first publish)'
    return None  # derived INDEX.md / *.index.md cards


def sync(plan):
    files = plan['files']
    if not files: return 'Nothing to publish.'
    lines = [f"Will publish to {where(plan)}:"] + [l for l in (_file(n, t) for n, t in files.items()) if l]
    derived = sum(1 for n in files if _file(n, files[n]) is None)
    if derived: lines.append(f'  plus {derived} generated index files')
    return '\n'.join(lines)


def team(plan):
    if plan.get('already'): return f"Already linked; the team copy is at {plan['path']}."
    action = plan.get('action', 'link')
    if action == 'unlink': return 'Will unlink the team. Your private notes stay; the team copy in .ws/team is kept.'
    privacy = plan.get('privacy') or ('attested' if plan.get('attested') else 'attestation required')
    return '\n'.join([f'Team {action}: {where(plan)}', f'Privacy: {privacy}',
                      'Nothing is published yet' + ('; ws sync publishes the team manifest.' if action == 'init' and plan.get('host') != 'folder' and 'source' not in plan else '.')])


def team_done(result):
    action = result.get('action', 'link')
    if action == 'unlink': return 'Team unlinked. Private notes and .ws/team are kept.'
    if result.get('bootstrap_pending'): return 'Team created and linked. Next: ws sync to publish the team manifest.'
    return 'Team created and linked.' if action == 'init' else 'Team linked.'


def entries(root):
    """{entry id: content hash} of the local team copy; {} when there is none."""
    found = {}
    try:
        for path in sorted((root / '.ws/team/entries').glob('*.md')):
            if not path.name.endswith('.index.md') and path.is_file():
                found[path.stem] = core.digest_text(path.read_text(encoding='utf-8', errors='replace'))
    except OSError: pass
    return found


def sync_line(before, after, published, pending=0):
    new = sum(1 for k in after if k not in before); updated = sum(1 for k in after if k in before and after[k] != before[k])
    pulled = f'pulled {new} new, {updated} updated' if new or updated else 'nothing new from the team'
    names = list(published or []); done = [n for n in names if ENTRY.fullmatch(n)]
    sent = (f'published {len(done)}.' if done else f'published {len(names)} file(s).' if names else
            f'not published ({pending} file(s) pending; run ws sync to publish).' if pending else 'nothing to publish.')
    return f'Team sync: {pulled}; {sent}'
