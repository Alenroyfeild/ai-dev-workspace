"""Explicit, previewed publication from approved blobs, never local history."""
import contextvars
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from . import cards, core, knowledge, sharing, team

AUTO_DEADLINE = contextvars.ContextVar('team_auto_deadline', default=None)

HINT = 'Resolve manually in .ws/team, retain local files, then preview ws sync again; never reset/force-push.'


def _git(clone, *args, data=None, index=None):
    deadline = AUTO_DEADLINE.get(); remaining = deadline-time.monotonic() if deadline is not None else 30
    if remaining <= 0: raise core.WsError('Automatic team pull timed out; run ws sync --pull-only manually.')
    env = dict(os.environ)
    for key in ('GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_NAMESPACE'): env.pop(key,None)
    if index: env['GIT_INDEX_FILE'] = str(index)
    try:
        return subprocess.run(['git','-c','core.hooksPath='+os.devnull,'-c','commit.gpgSign=false',
            '-C',str(clone),*args], input=data.encode('utf-8') if data is not None else None, env=env, capture_output=True, check=True, timeout=min(30,remaining)).stdout.decode('utf-8')
    except (OSError, UnicodeError, subprocess.SubprocessError): raise core.WsError('Team sync Git operation stopped. '+HINT)


def _remote(clone, remote, branch):
    line = _git(clone,'ls-remote','--heads','--',remote,'refs/heads/'+branch).split()
    if not line: return ''
    if len(line)!=2 or not re.fullmatch(r'[a-f0-9]{40,64}',line[0]): raise core.WsError('Invalid remote head. '+HINT)
    return line[0]


def _discard_index(clone):
    """INDEX.md is derived from the entries, so a local copy never blocks a pull; True if one was dropped."""
    state=_git(clone,'status','--porcelain=v1','-z','--','INDEX.md')
    if not state: return False
    if state.startswith('??'): (clone/'INDEX.md').unlink()
    else: _git(clone,'checkout','HEAD','--','INDEX.md')
    return True


def _pull(clone, head):
    index=clone/'INDEX.md'; saved=index.read_bytes() if index.is_file() else None
    dropped=_discard_index(clone)
    try: _git(clone,'merge','--ff-only','--no-edit','FETCH_HEAD')
    except core.WsError:
        if dropped and saved is not None: index.write_bytes(saved)  # the failed pull must not lose the local index
        dirty={e[3:] for e in _git(clone,'status','--porcelain=v1','-z','--untracked-files=all').split('\0') if e}
        names=sorted(dirty&set(_git(clone,'diff','--name-only','-z',head,'FETCH_HEAD').split('\0')))
        if not names: raise
        raise core.WsError(f'Resolve manually: the pull would overwrite local changes to {", ".join(names)} in {clone}. Keep a copy if you need it, then run '
                           f'`git -C {clone} checkout -- {" ".join(names)}` (untracked files: move them away) and `ws sync --pull-only`; never reset/force-push.') from None
    return dropped


def _index_current(root):
    """True when INDEX.md already equals what the entries generate, so it needs no separate approval."""
    return not any(p.name=='INDEX.md' for p in cards.plan(root,'team'))


def _view(root, pull, read_only=False):
    if core.config(root).get('team_workspace',{}).get('host')=='folder': raise core.WsError('Git sync cannot operate on a folder host; use the folder publication path.')
    bad=None
    try: knowledge._bases(root,'team')  # Validates the linked manifest and all path components.
    except team.ManifestError as exc:
        if not pull: raise
        bad=exc  # a pull may bring the fix; the manifest is checked again right after it
    cfg_text = sharing._text(sharing._safe(root,root/'workspace.json')); cfg=json.loads(cfg_text)
    link=cfg.get('team_workspace',{}); clone=sharing._safe(root,root/'.ws/team')
    if not link or link.get('path')!='.ws/team': raise core.WsError('Link a team first: run `ws team link <private-repo>`, or `ws team init <private-repo>` to create one.')
    metadata=sharing._safe(root,clone/'.git')
    if not metadata.is_dir(): raise core.WsError('Team clone requires its own Git directory; retain files and link again.')
    common=Path(_git(clone,'rev-parse','--git-common-dir').strip())
    if not common.is_absolute(): common=clone/common
    if common.resolve()!=metadata or Path(_git(clone,'rev-parse','--show-toplevel').strip()).resolve()!=clone:
        raise core.WsError('Git metadata/worktree is redirected; retain files and link again.')
    remote=link['remote']; host,_=team.remote_parts(remote)
    if host and os.environ.get('WS_OFFLINE')=='1': raise core.WsError('Offline: pending approvals remain local; sync later.')
    if _git(clone,'remote','get-url','--all','origin').strip()!=remote or _git(clone,'remote','get-url','--push','--all','origin').strip()!=remote:
        raise core.WsError('Team remote changed; link again before sync.')
    branch=_git(clone,'symbolic-ref','--short','HEAD').strip(); _git(clone,'check-ref-format','refs/heads/'+branch)
    base=_remote(clone,remote,branch)
    try: head=_git(clone,'rev-parse','--verify','HEAD').strip()
    except core.WsError: head=''
    if base!=head:
        if not base or not head or not pull: raise core.WsError('Local/remote history changed. '+HINT)
        _git(clone,'fetch','--no-tags','--',remote,branch)
        if _git(clone,'rev-parse','FETCH_HEAD').strip()!=base: raise core.WsError('Remote advanced; preview again.')
        _git(clone,'merge-base','--is-ancestor',head,base)
        dropped=_pull(clone,head); bad=None
        knowledge._bases(root,'team')  # pulled; still refuse to use an invalid manifest
        if dropped:  # regenerate the derived index so local entries stay listed after the pull
            try:
                changes={p:t for p,t in cards.plan(root,'team').items() if p.name=='INDEX.md'}
                if changes: cards.write(root,changes)
            except core.WsError as exc:  # the clone is already updated: report, do not fail the pull
                print(f'Warning: pulled, but INDEX.md was not regenerated: {exc}',file=sys.stderr)
    if bad: raise bad
    if read_only: return {'updated':base!=head,'head':base,'pushed':False}
    receipt=sharing._text(sharing._safe(root,root/'.ws/shares.json')); saved=json.loads(receipt or '{}')
    approved=saved.get('_artifacts:'+link['id'],{})
    if not isinstance(approved,dict): raise core.WsError('Invalid approval receipts. '+HINT)
    files={}; diff=''; total=0
    for entry in _git(clone,'status','--porcelain=v1','-z','--untracked-files=all').split('\0'):
        if not entry: continue
        if entry[:2]!='??' and entry[0]!=' ': raise core.WsError('Staged/conflicted changes are not publishing approval. '+HINT)
        name=entry[3:]
        if not re.fullmatch(r'(?:INDEX\.md|entries/[a-f0-9]{32}(?:\.index)?\.md|status/[A-Za-z0-9][A-Za-z0-9_.-]{0,39}\.json|team\.json)',name):
            raise core.WsError('Unapproved path blocks publication. '+HINT)
        path=sharing._safe(root,clone/name)
        if path.exists() and (not path.is_file() or path.stat().st_size>1024*1024): raise core.WsError('Unsafe/oversized shared file.')
        text=sharing._text(path) if path.exists() else None
        total+=len((text or '').encode())
        if len(files)>=1000 or total>16*1024*1024: raise core.WsError('Sync preview limit: 1000 files / 16 MiB; publish smaller batches.')
        if name=='team.json':
            expected={'kind':'ai-dev-workspace-team','schema_version':1,'id':link['id']}
            if base or text is None or json.loads(text)!=expected: raise core.WsError('Only the linked bootstrap manifest is approved.')
        elif name=='INDEX.md' and text is not None and _index_current(root): pass  # derived, never hand-written
        elif approved.get(name)!= (core.digest_text(text) if text is not None else ''):
            raise core.WsError('File differs from its sharing approval; run ws share again. '+HINT)
        sharing.check_public(root,name,text)
        old=_git(clone,'show',base+':'+name) if base and name in _git(clone,'ls-tree','--name-only',base,'--',name).splitlines() else ''
        files[name]=text
        diff+=''.join(difflib.unified_diff(old.splitlines(True),(text or '').splitlines(True),fromfile=name,tofile='approved/'+name))
    return {'remote':remote,'branch':branch,'base':base,'outgoing':'one approved projection commit' if files else 'none',
            'files':files,'diff':diff,'config_sha':core.digest_text(cfg_text),'receipts_sha':core.digest_text(receipt)}


def preview(root):
    if core.config(root).get('team_workspace',{}).get('host')=='folder':
        from . import folder_publish
        return folder_publish.preview(root)
    with core.lock(root): return _view(root,True)


def apply(root, plan):
    if core.config(root).get('team_workspace',{}).get('host')=='folder':
        from . import folder_publish
        return folder_publish.apply(root,plan)
    with core.lock(root):
        if _view(root,False)!=plan: raise core.WsError('Source, approvals or remote changed; preview again.')
        if not plan['files']: return {'pushed':False,'unchanged':True}
        clone=sharing._safe(root,root/'.ws/team'); link=core.config(root)['team_workspace']
        proof=link.get('privacy',{})
        if proof.get('remote')!=plan['remote']: raise core.WsError('Privacy consent does not match the remote.')
        team.privacy(plan['remote'],attest=proof.get('method')=='attested',verifier=proof.get('method') if proof.get('method') in ('gh','glab') else '')
        with tempfile.TemporaryDirectory(prefix='team-index-') as tmp:
            index=Path(tmp)/'index'; base=plan['base']
            _git(clone,'read-tree',base or '--empty',index=index)
            for name,text in plan['files'].items():
                if text is None: _git(clone,'update-index','--force-remove','--',name,index=index)
                else:
                    blob=_git(clone,'hash-object','-w','--no-filters','--stdin',data=text).strip()
                    _git(clone,'update-index','--add','--cacheinfo','100644,'+blob+','+name,index=index)
            tree=_git(clone,'write-tree',index=index).strip()
            commit=_git(clone,'-c','user.name=Workspace','-c','user.email=workspace@example.invalid',
                'commit-tree',tree,*(['-p',base] if base else []),data='Publish preview-approved team projections\n').strip()
        if _remote(clone,plan['remote'],plan['branch'])!=base: raise core.WsError('Remote advanced; preview again.')
        _git(clone,'push','--',plan['remote'],commit+':refs/heads/'+plan['branch'])
        try:
            _git(clone,'update-ref','refs/heads/'+plan['branch'],commit,base or '0'*40)
            _git(clone,'read-tree',commit)
        except core.WsError: raise core.WsError('Push succeeded at '+commit+'; local tracking needs repair. '+HINT)
        return {'pushed':True,'commit':commit,'files':list(plan['files'])}
