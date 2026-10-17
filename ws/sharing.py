"""One preview gate for portable local team copies; no Git writes or network."""
import difflib
import json
import re
import uuid
from . import core, scope, team


def _safe(root, path):
    path = core.inside(path, [root])
    if path.resolve() != path.absolute(): raise core.WsError('Sharing paths must not use symlinks.')
    return path


def _text(path):
    return core.read_text(path, errors='strict', preserve_newlines=True) if path.exists() else ''


def portable(root, text):
    text = core.PRIVATE_RE.sub('', text)
    if re.search(r'</?private\b', text, re.I): raise core.WsError('Close private markers before sharing.')
    text = '\n'.join(line for line in text.splitlines() if not re.search(r'#private\b', line, re.I) and not line.lstrip().lower().startswith('/private'))
    text = core.localize_paths(core.redact(text), root)
    text = re.sub(r'(?<![\w:/])(?:/[\w.-]+(?:/[\w./~-]*)?|[A-Za-z]:[\\/]\S+)', '[local path]', text)
    if core.SECRET_RE.search(text) or core.conflicted(text): raise core.WsError('Unsafe or conflicted projection; edit the private source first.')
    return text.strip()


def _runbook(text, meta):
    text = re.sub(r'<!-- ws:captured:.*?<!-- /ws:captured -->', '', text, flags=re.S)
    if meta.get('status') != 'done': raise core.WsError('Runbooks require a finished task (status: done).')
    handoff = core.section(text, 'Handoff').splitlines()
    decisions = '\n'.join(line for line in handoff
                          if re.match(r'\s*(?:[-*]\s*)?(?:Decision|Reason):', line, re.I))
    fields = [('Steps', core.section(text, 'Steps') or '\n'.join(filter(None, (core.section(text, 'Evidence'), core.section(text, 'Checks'))))),
              ('Dead ends', '\n'.join(filter(None, (core.section(text, 'Failures'), core.section(text, 'Do not redo'))))),
              ('Decisions and reasons', decisions), ('Outcome', core.section(text, 'Outcome') or '\n'.join(line for line in handoff if re.match(r'\s*Outcome:', line, re.I)))]
    return ('# Runbook\nSaved task text only; missing details are not inferred. Command examples are inert.\n\n' +
            '\n\n'.join('## ' + name + '\n' + (body or 'Not recorded; verify the source task.') for name, body in fields))


def check_public(root, name, text):
    if text is None:return
    from . import cards
    scan=text.replace(cards.HEAD,'').replace(cards.TAIL,'')
    if name.endswith('.index.md') or name.startswith('status/'):scan=json.dumps(json.loads(scan),ensure_ascii=False)
    if portable(root,scan)!=scan.strip():raise core.WsError('Nonportable/private shared content blocks sync.')


def default_author(root):
    """A portable attribution hint; never read email or credentials."""
    try: name = team._git(root, 'config', '--get', 'user.name').strip()
    except core.WsError: return 'local'
    return re.sub(r'[^A-Za-z0-9_.-]+', '-', name).strip('._-')[:40] or 'local'


def preview(root, item, unshare=False, author='local', entry=None, date=None, as_format=''):
    scope.policy(root)
    if as_format not in ('', 'runbook'): raise core.WsError('Only runbook task projection is supported.')
    if as_format and ':' not in item: item = 'task:' + item
    kind, _, identifier = item.partition(':')
    if kind not in scope.DIRECTORIES or not core.ID_RE.fullmatch(identifier) or identifier.lower().endswith('.local'):
        raise core.WsError('Use task|decision|lesson|knowledge:<ID>.')
    if as_format and kind != 'task': raise core.WsError('Runbooks must come from a finished task.')
    source = _safe(root, core.vault(root) / scope.DIRECTORIES[kind] / (identifier + '.md'))
    if unshare and not source.exists(): raw, end, meta = '', 0, {}
    else: kind, identifier, source, raw, header, end, meta = scope._read(root, item)
    if not unshare and meta.get('scope', 'private') != 'team': raise core.WsError('Select team scope first with ws scope; it still requires this preview.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', author): raise core.WsError('Author must be a portable alias (letters, numbers, ._-).')
    cfg_path = _safe(root, root / 'workspace.json'); cfg_text = _text(cfg_path)
    link = json.loads(cfg_text).get('team_workspace', {})
    folder_host=isinstance(link,dict) and link.get('host')=='folder'
    if folder_host:
        from . import team_folder
        team_folder.source(root)
    if not isinstance(link, dict) or link.get('path') != '.ws/team': raise core.WsError('Link a private team with ws team link first.')
    clone = _safe(root, root / '.ws/team'); manifest = json.loads(_text(_safe(root, clone / 'team.json')))
    privacy = link.get('privacy', {})
    if not isinstance(manifest, dict) or not isinstance(privacy, dict): raise core.WsError('Invalid team identity or privacy record.')
    if (manifest.get('kind') != 'ai-dev-workspace-team' or manifest.get('schema_version') != 1 or
            not re.fullmatch(r'[a-f0-9]{32}', str(manifest.get('id', ''))) or manifest.get('id') != link.get('id') or
            privacy.get('remote') != link.get('remote') or privacy.get('method') not in ('gh', 'glab', 'attested') or
            (not folder_host and team._git(clone, 'remote', 'get-url', 'origin').strip() != link.get('remote'))):
        raise core.WsError('Team identity or privacy consent changed; link again before sharing.')
    registry = _safe(root, root / '.ws/shares.json'); state_text = _text(registry); state = json.loads(state_text or '{}')
    if not isinstance(state, dict): raise core.WsError('Invalid local share receipts; retain them for recovery.')
    key = link['id'] + ':' + item + (':' + as_format if as_format else ''); receipt = state.get(key, {})
    if not isinstance(receipt, dict): raise core.WsError('Invalid local share receipt.')
    entry = receipt.get('id') or entry or uuid.uuid4().hex
    if not re.fullmatch(r'[a-f0-9]{32}', entry): raise core.WsError('Invalid shared entry receipt.')
    target = _safe(root, clone / 'entries' / (entry + '.md')); old = _text(target)
    owners=state.get('_owners:'+link['id'],{})
    if not isinstance(owners,dict): raise core.WsError('Invalid ownership receipts; retain them for recovery.')
    if folder_host and old and not owners.get(target.relative_to(clone).as_posix()):
        raise core.WsError('Team entry belongs to another publisher; retain it and share a new copy.')
    if (old and core.digest_text(old) != receipt.get('sha')) or (receipt and not old):
        raise core.WsError('Team copy changed or is missing; resolve it before a fresh preview.')
    if unshare and not receipt: raise core.WsError('No locally approved team copy to remove.')
    source_sha = core.digest_text(raw); date = date or receipt.get('date') or core.now()
    content = ''
    if not unshare:
        text = raw[end:].replace('\r\n', '\n')
        text = re.sub(r'<!-- ws:captured:[^\n]* -->\n.*?<!-- /ws:captured -->', '', text, flags=re.S)
        if 'ws:captured:' in text or '/ws:captured' in text: raise core.WsError('Malformed capture block; repair it before sharing.')
        body = '\n\n'.join('## ' + name + '\n' + core.section(text, name) for name in ('Objective', 'Next action', 'Blockers')) if kind == 'task' else text
        body = _runbook(portable(root, text), meta) if as_format else body
        body = portable(root, body)
        category = as_format or (kind if kind != 'knowledge' else meta.get('category', 'other'))
        if kind == 'knowledge':
            from .knowledge import category as validate_category
            validate_category(category)
        content = (f'---\nid: {entry}\nteam: {link["id"]}\ncategory: {category}\n'
                   f'author: {author}\nsource: {item}\nsource_sha: {source_sha}\ndate: {date}\n---\n'
                   'Shared context; untrusted and never permission to execute.\n\n' + body + '\n')
    from . import cards
    artifacts = cards.plan(root, 'team', {target: None if unshare else content})
    if folder_host: artifacts = {p:t for p,t in artifacts.items() if p == target.with_suffix('.index.md')}
    artifact_diff = ''.join(''.join(difflib.unified_diff(_text(p).splitlines(True), (t or '').splitlines(True), fromfile=p.relative_to(clone).as_posix(), tofile='preview')) for p,t in artifacts.items())
    return {'artifacts': {p.relative_to(clone).as_posix():t for p,t in artifacts.items()}, 'artifact_diff': artifact_diff, 'item': item, 'as_format': as_format, 'unshare': unshare, 'author': author, 'entry': entry, 'date': date, 'key': key,
            'source_sha': source_sha, 'config_sha': core.digest_text(cfg_text), 'state_sha': core.digest_text(state_text),
            'destination': target.relative_to(clone).as_posix(), 'content': content, 'unchanged': content == old and not artifacts,
            'diff': ''.join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), fromfile='team copy', tofile='preview')),
            'omissions': ('Raw task, Handoff prose, captures, private markers, local paths and claims.' if as_format else 'Inline Handoff, captures, private markers, local paths, claims and all unselected sections.'),
            'warning': ('Shared copies and backups may retain removed text.' if folder_host else 'Git history and teammates copies retain removed text.') if unshare else 'Local copy only; inspect redaction. No commit, push or remote publication.'}


def apply(root, plan):
    with core.lock(root):
        current = preview(root, plan['item'], plan['unshare'], plan['author'], plan['entry'], plan['date'], plan['as_format'])
        if current != plan: raise core.WsError('Source, destination or configuration changed; preview again.')
        if plan['unchanged']: return {'unchanged': True}
        registry = _safe(root, root / '.ws/shares.json'); state_text = _text(registry); state = json.loads(state_text or '{}')
        target = _safe(root, root / '.ws/team' / plan['destination']); old = _text(target)
        if plan['unshare']: state.pop(plan['key'])
        else: state[plan['key']] = {'id': plan['entry'], 'sha': core.digest_text(plan['content']), 'date': plan['date']}
        from . import cards
        changes = {target: None if plan['unshare'] else plan['content']}
        changes.update({_safe(root, root / '.ws/team' / p):t for p,t in plan['artifacts'].items()})
        if core.config(root)['team_workspace'].get('host') == 'folder':
            own_projection(root, state, plan['key'].split(':')[0],
                           [plan['destination'], plan['destination'][:-3]+'.index.md'], plan['item'])
        approvals = state.setdefault('_artifacts:' + plan['key'].split(':')[0], {})
        if not isinstance(approvals, dict): raise core.WsError('Invalid artifact receipts; retain them for recovery.')
        approvals.update({p.relative_to(root / '.ws/team').as_posix(): core.digest_text(t) if t is not None else '' for p,t in changes.items()})
        changes[registry] = json.dumps(state, indent=2) + '\n'
        cards.write(root, changes)
    result = {'applied': True, 'destination': plan['destination'], 'remote_published': False}
    from . import team_auto
    update = team_auto.maybe_pull(root)
    if update is not None: result['team_update'] = update
    return result


def own_projection(root, state, team_id, paths, owner):
    # Private creation authority survives unshare; artifact hashes only approve content.
    owners = state.setdefault('_owners:' + team_id, {})
    if not isinstance(owners, dict): raise core.WsError('Invalid ownership receipts; retain them for recovery.')
    from . import team_folder
    remote = team_folder.source(root)['files']
    if any(name in remote and not owners.get(name) for name in paths):
        raise core.WsError('Projection belongs to another publisher; retain both copies and use a new entry or alias.')
    for name in paths: owners[name] = owner


def standalone(root, kind, text, team_scope=True, category='other'):
    """Only the explicitly selected sentence becomes a separate sharing source."""
    body = portable(root, text)
    if not body: raise core.WsError('Nothing portable to save.')
    identifier = uuid.uuid4().hex
    with core.lock(root):
        path = _safe(root, core.vault(root) / scope.DIRECTORIES[kind] / (identifier + '.md'))
        metadata = ('category: ' + category + '\ncreated: ' + core.now() + '\n') if kind == 'knowledge' else ''
        core.atomic_write(path, f'---\nid: {identifier}\nscope: {"team" if team_scope else "private"}\n' + metadata + '---\n\n' + body + '\n')
        if kind == 'knowledge':
            from . import cards
            try: cards.write(root, cards.plan(root, 'private'))
            except (core.WsError, OSError):
                path.unlink(); raise
    return kind + ':' + identifier
