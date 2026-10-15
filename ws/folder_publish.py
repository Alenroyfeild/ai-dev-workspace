"""Explicit receipt-gated folder publication; private recovery copies, no cloud API."""
import difflib
import json
import uuid
from pathlib import Path
from . import cards, core, folder_io, sharing, team_folder


def _normal(text):
    return text.replace('\r\n','\n').replace('\r','\n') if text is not None else None


def _view(root):
    data=team_folder.source(root);local=team_folder.snapshot(root,root/'.ws/team',local=True)['files']
    base_text=sharing._text(sharing._safe(root,root/'.ws/folder-base.json'));base=json.loads(base_text)
    receipts=sharing._text(sharing._safe(root,root/'.ws/shares.json'));approved=json.loads(receipts or '{}').get('_artifacts:'+data['team'],{})
    if not isinstance(base,dict) or not isinstance(approved,dict):raise core.WsError('Invalid folder baseline/approvals; retain local files.')
    hashes=team_folder._hashes(local);remote=team_folder._hashes(data['files']);files={};diff=''
    for name in sorted(set(base)|set(local)):
        if base.get(name)==hashes.get(name):continue
        text=local.get(name)
        if name=='team.json' or approved.get(name)!=(core.digest_text(text) if text is not None else ''):
            raise core.WsError('File differs from its sharing approval; run ws share again: '+name)
        if remote.get(name)!=base.get(name) and remote.get(name)!=hashes.get(name):
            raise core.WsError('Team folder conflict: '+name+'. Retain both copies and resolve manually before another preview.')
        sharing.check_public(root,name,text)
        files[name]=text;diff+=''.join(difflib.unified_diff(data['files'].get(name,'').splitlines(True),(text or '').splitlines(True),fromfile=name,tofile='approved/'+name))
    return {'host':'folder','remote':data['source'],'identity':data['identity'],'files':files,'diff':diff,
            'source_hashes':remote,'local_hashes':hashes,'base_sha':core.digest_text(base_text),
            'receipts_sha':core.digest_text(receipts),'config_sha':core.digest_text(sharing._text(root/'workspace.json'))}


def preview(root):
    with core.lock(root):
        plan=_view(root)
        if not plan['files']:team_folder.pull(root);plan=_view(root)
        return plan


def apply(root,plan):
    with core.lock(root):
        if _view(root)!=plan:raise core.WsError('Source, approvals or workspace changed; preview again.')
        if not plan['files']:return {'published':False,'unchanged':True}
        folder=Path(plan['remote']);identity=plan['identity'];data=team_folder.source(root)['files']
        before={name:folder_io.read(folder,identity,name) for name in plan['files']}
        if any((core.digest_text(_normal(text)) if text is not None else None)!=plan['source_hashes'].get(name) for name,text in before.items()):
            raise core.WsError('Source changed before backup; preview again.')
        backup=sharing._safe(root,root/'.ws/backups'/('folder-'+uuid.uuid4().hex)/'state.json')
        cards.write(root,{backup:json.dumps({'source':str(folder),'identity':identity,'files':before},ensure_ascii=False,indent=2)+'\n'})
        attempted=[];wanted=dict(data)
        try:
            for name,text in plan['files'].items():
                if text is None:wanted.pop(name,None)
                else:wanted[name]=text
                if _normal(before[name])==text:continue
                attempted.append(name);folder_io.replace(folder,identity,name,text,before[name])
            fresh=team_folder.source(root)['files']
            if fresh!=wanted:raise core.WsError('Source changed during publication.')
        except (OSError,ValueError,core.WsError) as error:
            for name in reversed(attempted):
                try:
                    current=folder_io.read(folder,identity,name)
                    if current==plan['files'][name]:folder_io.replace(folder,identity,name,before[name],current)
                except (OSError,ValueError,core.WsError):pass
            raise core.WsError('Folder publication stopped; retain local approvals and inspect private backup '+str(backup.relative_to(root))+'. '+str(error))
        try:
            local=root/'.ws/team';current=team_folder.snapshot(root,local,local=True)['files']
            if team_folder._hashes(current)!=plan['local_hashes']:raise core.WsError('Local mirror changed.')
            changes={local/name:fresh.get(name) for name in set(current)|set(fresh) if current.get(name)!=fresh.get(name)}
            changes[root/'.ws/folder-base.json']=json.dumps(team_folder._hashes(fresh));cards.write(root,changes)
        except (OSError,ValueError,core.WsError):
            raise core.WsError('Folder published; local refresh needs repair. Retain both copies and preview ws sync again. Backup: '+str(backup.relative_to(root)))
        return {'published':True,'host':'folder','files':list(plan['files']),'backup':str(backup.relative_to(root))}
