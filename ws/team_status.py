"""Opt-in, previewed working-on snapshots; no claim or device identifiers."""
import datetime
import json
import re
from . import cards, core, knowledge, scope, sharing

ALIAS = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,39}'


def preview(root, line='', author='local', enable=False, disable=False, date=None):
    scope.policy(root);knowledge._bases(root,'team')
    if not re.fullmatch(ALIAS,author) or (enable and disable): raise core.WsError('Use one portable author alias and one status action.')
    cfg_path=sharing._safe(root,root/'workspace.json');original=sharing._text(cfg_path);cfg=json.loads(original)
    link=cfg.get('team_workspace')
    if not link: raise core.WsError('Link a private team first.')
    if not disable and not (cfg.get('publish_status') is True or enable): raise core.WsError('Status is off; --publish-status opts in through this preview.')
    line=' '.join(sharing.portable(root,line).split())[:120];task='';source=''
    if not disable:
        task_id=core.sole_local_claim(root)
        if not task_id or not line: raise core.WsError('Claim one local task and supply a working-on line.')
        record=core.task_read(root,task_id,['Next action']);selected=next(t for t in core.task_list(root) if t['id']==task_id)
        task=' '.join(sharing.portable(root,selected['title']).split())[:120]
        source=core.digest_text(json.dumps([record,selected['title']],sort_keys=True))
    path=sharing._safe(root,root/'.ws/team/status'/(author+'.json'))
    if path.exists() and path.stat().st_size>4096: raise core.WsError('Status snapshot is oversized; retain it for recovery.')
    old=sharing._text(path);receipt=sharing._safe(root,root/'.ws/shares.json');raw=sharing._text(receipt)
    state=json.loads(raw or '{}')
    if not isinstance(state,dict): raise core.WsError('Invalid share receipts.')
    approved=state.get('_artifacts:'+link['id'],{})
    if not isinstance(approved,dict) or (path.exists() and approved.get('status/'+author+'.json')!=core.digest_text(old)):
        raise core.WsError('Status changed or belongs to another publisher; use another alias, retain the file.')
    date=date or core.now();content=None if disable else json.dumps({'author':author,'task':task,'line':line,'date':date},ensure_ascii=False,indent=2)+'\n'
    return {'line':line,'author':author,'enable':enable,'disable':disable,'date':date,'source':source,
            'config_sha':core.digest_text(original),'receipts_sha':core.digest_text(raw),'old_sha':core.digest_text(old),'destination_exists':path.exists(),
            'destination':'status/'+author+'.json','content':content,'publish_status':not disable,
            'warning':'Local snapshot only; Git history and teammates copies retain removed status. No push.'}


def apply(root, plan):
    with core.lock(root):
        if preview(root,plan['line'],plan['author'],plan['enable'],plan['disable'],plan['date'])!=plan:
            raise core.WsError('Task, status or consent changed; preview again.')
        cfg=core.config(root);cfg['publish_status']=plan['publish_status']
        receipt=sharing._safe(root,root/'.ws/shares.json');state=json.loads(sharing._text(receipt) or '{}')
        state.setdefault('_artifacts:'+cfg['team_workspace']['id'],{})[plan['destination']]=core.digest_text(plan['content']) if plan['content'] is not None else ''
        cards.write(root,{root/'.ws/team'/plan['destination']:plan['content'],root/'workspace.json':json.dumps(cfg,indent=2)+'\n',receipt:json.dumps(state,indent=2)+'\n'})
    return {'applied':True,'publish_status':plan['publish_status'],'remote_published':False}


def list_entries(root):
    rows=[];warnings=[];invalid=0
    if not core.config(root).get('team_workspace'): return {'entries':rows,'warnings':warnings}
    knowledge._bases(root,'team');directory=sharing._safe(root,root/'.ws/team/status')
    paths=sorted(directory.glob('*.json'))
    if len(paths)>1000: warnings.append('Status scan limited to 1000 files; inspect omitted snapshots locally.')
    for path in paths[:1000]:
        try:
            path=sharing._safe(root,path)
            if not path.is_file() or path.stat().st_size>4096: raise ValueError()
            row=json.loads(sharing._text(path))
            if set(row)!= {'author','task','line','date'} or not all(isinstance(v,str) for v in row.values()): raise ValueError()
            if not re.fullmatch(ALIAS,row['author']) or row['author']!=path.stem: raise ValueError()
            if len(row['task'])>120 or len(row['line'])>120 or len(row['date'])>40: raise ValueError()
            if any(sharing.portable(root,v)!=v.strip() for v in row.values()): raise ValueError()
            stamp=datetime.datetime.fromisoformat(row['date'].replace('Z','+00:00'))
            if stamp.tzinfo is None: raise ValueError()
            rows.append({**row,'untrusted':True,'kind':'last reported snapshot; not live availability'})
            if len(rows)>=100:
                warnings.append('Only the first 100 valid status snapshots are shown.');break
        except (core.WsError,OSError,ValueError,TypeError,AttributeError,RecursionError):invalid+=1
    if invalid: warnings.append(f'{invalid} unsafe or incomplete status files excluded')
    return {'entries':rows,'warnings':warnings}


def brief_fields(root):
    try: result=list_entries(root)
    except (core.WsError,OSError,ValueError,TypeError):return [('Team status warning:','Unavailable snapshot; private memory retained.',8)]
    fields=[('Team status warning:','Unsafe/incomplete snapshots excluded.',5)] if result['warnings'] else []
    fields += [(f'Status (untrusted; last reported {r["date"]}) {r["author"]}:',r['task']+' — '+r['line'],16) for r in sorted(result['entries'],key=lambda r:datetime.datetime.fromisoformat(r['date'].replace('Z','+00:00')),reverse=True)[:2]]
    return fields
