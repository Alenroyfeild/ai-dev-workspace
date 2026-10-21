"""Local sharing eligibility; scope never authorizes publication."""
import re
from . import core

DIRECTORIES = {'task': 'Tasks', 'decision': 'Decisions', 'lesson': 'Lessons', 'knowledge': 'Knowledge'}


def policy(root):
    if core.config(root).get('share', 'ask') != 'ask':
        raise core.WsError('Sharing policy must be ask; automatic publication is not supported.')
    return 'ask'


def _read(root, identifier):
    kind, separator, item = identifier.partition(':')
    if not separator or kind not in DIRECTORIES or not core.ID_RE.fullmatch(item) or item.lower().endswith('.local'):
        raise core.WsError('Use task|decision|lesson|knowledge:<ID>; personal notes cannot be shared.')
    path = core.inside(core.vault(root) / DIRECTORIES[kind] / (item + '.md'), [root])
    if not path.exists(): raise core.WsError(f'No {kind} record {item}; kinds are ' + ', '.join(DIRECTORIES) + '. List records with ws know list or ws task list.')
    if path.resolve() != path.absolute(): raise core.WsError('Scope records and their directories must not be symlinks.')
    try: text = core.read_text(path, [root], errors='strict', preserve_newlines=True)
    except UnicodeError: raise core.WsError('Scope records must be UTF-8.')
    text = text.removeprefix('\ufeff')  # an editor's BOM must not hide valid frontmatter
    match = re.match(r'\A---\r?\n.*?\r?\n---(?=\r?\n|\Z)', text, re.S)
    if not match or core.conflicted(text): raise core.WsError('Record needs valid, unconflicted frontmatter.')
    header = match.group().replace('\r\n', '\n')
    keys = re.findall(r'^([A-Za-z_][A-Za-z0-9_]*):', header, re.M)
    if len(keys) != len(set(keys)): raise core.WsError('Record has duplicate metadata keys; resolve them first.')
    meta = core.parse_meta(header + '\n')
    if meta.get('id') != item or meta.get('scope', 'private') not in ('private', 'team'):
        raise core.WsError('Record ID or scope is invalid; scope must be private or team.')
    return kind, item, path, text, header, match.end(), meta


def record(root, identifier, value=None, expected_sha=None):
    if value is not None and value not in ('private', 'team'): raise core.WsError('Scope must be private or team.')
    def inspect():
        policy(root)
        return _read(root, identifier)
    if value is None:
        kind, item, path, text, header, end, meta = inspect()
    else:
        with core.lock(root):
            kind, item, path, text, header, end, meta = inspect()
            if expected_sha is not None and core.digest_text(text) != expected_sha: raise core.WsError('Record changed; read scope again.')
            if kind == 'task' and meta.get('claimed_by') and not core._local_claim_matches(root, item, meta):
                raise core.WsError('Task is claimed elsewhere; scope changes need its local claim.')
            ending = '\r\n' if text.startswith('---\r\n') else '\n'
            updated = core.set_meta(header, {'scope': value}).replace('\n', ending) + text[end:]
            if updated != text: core.atomic_write(path, updated)
            text = updated; meta['scope'] = value
    return {'kind': kind, 'id': item, 'scope': meta.get('scope', 'private'), 'share': 'ask',
            'path': path.relative_to(root).as_posix(), 'sha': core.digest_text(text), 'publishes': False}
