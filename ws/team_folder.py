"""Attested existing folder hosts: stable local snapshots, no source writes."""
import json
import re
from pathlib import Path
from . import cards, core, knowledge, sharing

HINT='Folder pull stopped; retain both copies, resolve conflicts/partial files or pending local edits manually, then retry.'


def snapshot(root, folder, local=False):
    folder=Path(folder).expanduser().absolute()
    if local and folder != sharing._safe(root,root/'.ws/team'): raise core.WsError(HINT)
    if folder.resolve()!=folder or not folder.is_dir() or (not local and (folder==root or root in folder.parents or folder in root.parents)):
        raise core.WsError('Use a real dedicated folder outside the private workspace, without symlinks.')
    info=folder.stat(); files={}; total=0
    for directory in (folder,folder/'entries',folder/'status'):
        if not directory.exists(): continue
        if directory.resolve()!=directory or not directory.is_dir(): raise core.WsError(HINT)
        for path in directory.iterdir():
            name=path.relative_to(folder).as_posix()
            if name in ('entries','status') and path.is_dir() and not path.is_symlink(): continue
            if name=='.DS_Store' and not path.is_symlink(): continue
            if not re.fullmatch(r'team\.json|INDEX\.md|entries/[a-f0-9]{32}(?:\.index)?\.md|status/[A-Za-z0-9][A-Za-z0-9_.-]{0,39}\.json',name):
                raise core.WsError('Unexpected/conflict-copy file: '+name+'. '+HINT)
            if path.resolve()!=path or not path.is_file() or path.stat().st_size>1024*1024: raise core.WsError(HINT)
            text=core.read_text(path,[folder],errors='strict'); total+=len(text.encode())
            if len(files)>=1000 or total>8*1024*1024: raise core.WsError('Folder snapshot exceeds 1000 files / 8 MiB.')
            files[name]=text
    manifest=json.loads(files.get('team.json','{}'));team=manifest.get('id') if isinstance(manifest,dict) else None
    if (not isinstance(manifest,dict) or manifest.get('kind')!='ai-dev-workspace-team' or manifest.get('schema_version')!=1 or
        not re.fullmatch(r'[a-f0-9]{32}',str(team))): raise core.WsError('Folder needs a valid team.json from its host.')
    for name,text in files.items():
        if name.startswith('entries/') and not name.endswith('.index.md'):
            knowledge._read(root,root/'.ws/team'/name,'team',team,raw=text,include_all=True)
            card=files.get(name[:-3]+'.index.md','')
            if card.count(cards.HEAD)!=1 or card.count(cards.TAIL)!=1: raise core.WsError('Incomplete folder record/card. '+HINT)
            data=json.loads(card.split(cards.HEAD)[1].split(cards.TAIL)[0])
            if (not isinstance(data,dict) or data.get('schema')!=1 or data.get('source_bytes')!=len(text.encode()) or
                not isinstance(data.get('row'),dict) or data['row'].get('revision')!=core.digest_text(text)):
                raise core.WsError('Record/card changed during sync. '+HINT)
        elif name.endswith('.index.md') and name.replace('.index.md','.md') not in files: raise core.WsError('Orphan folder card. '+HINT)
        elif name.startswith('status/'):
            row=json.loads(text)
            if not isinstance(row,dict) or set(row)!={'author','task','line','date'} or not all(isinstance(v,str) for v in row.values()):
                raise core.WsError('Incomplete status snapshot. '+HINT)
    return {'files':files,'identity':[info.st_dev,info.st_ino],'team':team,'source':str(folder)}


def _hashes(files):
    return {name:core.digest_text(text) for name,text in files.items()}


def link(root, folder, apply=False, attest=False, auto_pull=False, expected=None):
    root=Path(root).resolve(); cfg_path=sharing._safe(root,root/'workspace.json');original=sharing._text(cfg_path);cfg=json.loads(original)
    data=snapshot(root,folder);target=sharing._safe(root,root/'.ws/team');linked=cfg.get('team_workspace')
    if linked:
        if not isinstance(linked,dict) or linked.get('host')!='folder' or linked.get('remote')!=data['source']: raise core.WsError('Unlink the current team first.')
        if linked.get('id')!=data['team'] or linked.get('privacy',{}).get('identity')!=data['identity']: raise core.WsError('Folder identity changed; unlink and attest again.')
        knowledge._bases(root,'team');return {'already':True,'path':str(target)}
    if target.exists(): raise core.WsError('Local team mirror exists; preserve or move it before linking.')
    plan={'host':'folder','source':data['source'],'identity':data['identity'],'team':data['team'],'path':str(target),
          'files':sorted(data['files']),'snapshot_sha':core.digest_text(json.dumps(data['files'],sort_keys=True)),
          'sha':core.digest_text(original),'auto_pull':bool(auto_pull),'privacy':'attested' if attest else 'attestation required','publishes':False}
    if not apply:return plan
    if not attest:raise core.WsError('Confirm this folder is private to your team with --attest-private.')
    with core.lock(root):
        if link(root,folder,attest=attest,auto_pull=auto_pull)!=expected or snapshot(root,folder)!=data:raise core.WsError('Folder/workspace changed; preview again.')
        privacy={'method':'attested','remote':data['source'],'identity':data['identity'],'manifest_sha':core.digest_text(data['files']['team.json']),'date':core.now()}
        cfg['team_workspace']={'id':data['team'],'host':'folder','path':'.ws/team','remote':data['source'],'privacy':privacy,'auto_pull':bool(auto_pull)}
        changes={target/name:text for name,text in data['files'].items()}
        changes.update({root/'.ws/folder-base.json':json.dumps(_hashes(data['files'])),cfg_path:json.dumps(cfg,indent=2)+'\n'})
        cards.write(root,changes)
    return {**plan,'applied':True}


def pull(root):
    link=core.config(root)['team_workspace'];proof=link.get('privacy',{});data=snapshot(root,link['remote'])
    if (proof.get('method')!='attested' or proof.get('remote')!=data['source'] or proof.get('identity')!=data['identity'] or
        link.get('id')!=data['team'] or proof.get('manifest_sha')!=core.digest_text(data['files']['team.json'])): raise core.WsError('Folder identity/attestation changed; link again.')
    base=sharing._safe(root,root/'.ws/folder-base.json');saved=json.loads(sharing._text(base));local=root/'.ws/team'
    # Local snapshots use the same strict inventory; never discard pending edits.
    current=snapshot(root,local,local=True)['files']
    if _hashes(current)!=saved: raise core.WsError(HINT)
    if snapshot(root,link['remote'])!=data: raise core.WsError('Folder changed during read. '+HINT)
    changes={local/name:data['files'].get(name) for name in set(current)|set(data['files']) if current.get(name)!=data['files'].get(name)}
    updated=bool(changes)
    if changes:
        changes[base]=json.dumps(_hashes(data['files']));cards.write(root,changes)
    return {'updated':updated,'pushed':False,'host':'folder'}
