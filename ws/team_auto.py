"""Consented read-only pulls and previewed per-user daily launchd jobs."""
import hashlib
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from . import core, knowledge, sharing, team_sync


def pull(root, automatic=False):
    with core.lock(root):
        if automatic and core.config(root).get('team_workspace',{}).get('auto_pull') is not True:
            return {'skipped':True,'pushed':False}
        if core.config(root).get('team_workspace',{}).get('host')=='folder':
            from . import team_folder
            return team_folder.pull(root)
        token=team_sync.AUTO_DEADLINE.set(time.monotonic()+4) if automatic else None
        try: return team_sync._view(root,True,read_only=True)
        finally:
            if token is not None: team_sync.AUTO_DEADLINE.reset(token)


def maybe_pull(root):
    try:
        if core.config(root).get('team_workspace',{}).get('auto_pull') is not True: return None
        return pull(root,automatic=True)
    except (core.WsError,OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):
        return {'warning':'Team pull stopped; local files retained. Run ws sync --pull-only for the resolution hint.','pushed':False}


def _launch(*args):
    return subprocess.run(['launchctl',*args],capture_output=True,timeout=10).returncode


def schedule(root, at, apply=False, expected=None):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',at): raise core.WsError('Daily time must be HH:MM (local time).')
    cfg=core.config(root)
    if cfg.get('team_workspace',{}).get('auto_pull') is not True: raise core.WsError('Automatic pulls need explicit link consent (team_workspace.auto_pull=true).')
    knowledge._bases(root,'team')
    hour,minute=map(int,at.split(':'));label='com.ai-dev-workspace.team-pull.'+core.digest_text(str(root))[:12]
    argv=[sys.executable,str(core.KIT/'bin/ws'),'--workspace-root',str(root),'sync','--pull-only','--automatic']
    plan={'label':label,'time':at,'argv':argv,'supported':sys.platform=='darwin','config_sha':core.digest_text(json.dumps(cfg,sort_keys=True))}
    if not plan['supported']:
        plan['suggestion']=('Task Scheduler: run this argv daily at '+at if sys.platform=='win32' else f'cron: {minute} {hour} * * * '+shlex.join(argv).replace('%',r'\%'))
        return plan
    path=core.inside(Path.home()/'Library/LaunchAgents'/(label+'.plist'),[Path.home()])
    if path.resolve()!=path.absolute(): raise core.WsError('Scheduler path must not use symlinks.')
    if path.exists() and (not path.is_file() or path.stat().st_size>16384): raise core.WsError('Scheduler file is unsafe/oversized; retain it.')
    old=path.read_bytes() if path.is_file() else b''
    if path.exists():
        try: prior=plistlib.loads(old)
        except Exception: raise core.WsError('Unmanaged scheduler file; preserve it before continuing.')
        if (not isinstance(prior,dict) or set(prior)!= {'Label','ProgramArguments','StartCalendarInterval','EnvironmentVariables'} or
            prior.get('Label')!=label or prior.get('ProgramArguments')!=argv or prior.get('EnvironmentVariables')!={'WS_MANAGED_TEAM_PULL':label}):
            raise core.WsError('Scheduler file changed or is unmanaged; preserve it before continuing.')
        calendar=prior.get('StartCalendarInterval')
        if (not isinstance(calendar,dict) or set(calendar)!={'Hour','Minute'} or
            any(type(calendar[key]) is not int or not 0<=calendar[key]<limit for key,limit in (('Hour',24),('Minute',60)))):
            raise core.WsError('Scheduler interval is unmanaged; preserve it before continuing.')
        plan['previous_time']=f"{calendar['Hour']:02}:{calendar['Minute']:02}"
    data={'Label':label,'ProgramArguments':argv,'StartCalendarInterval':{'Hour':hour,'Minute':minute},'EnvironmentVariables':{'WS_MANAGED_TEAM_PULL':label}}
    plan.update(path=str(path),old_sha=hashlib.sha256(old).hexdigest(),exists=path.exists(),content=plistlib.dumps(data).decode('utf-8'))
    if not apply: return plan
    with core.lock(root):
        if schedule(root,at)!=expected: raise core.WsError('Scheduler or consent changed; preview again.')
        domain='gui/'+str(getattr(os,'getuid',lambda:0)())
        try:
            if old==plan['content'].encode() and _launch('print',domain+'/'+label)==0: return {'unchanged':True}
            core.atomic_write(path,plan['content'])
            if old: _launch('bootout',domain+'/'+label)
            if _launch('bootstrap',domain,str(path))!=0: raise OSError('launchd registration failed')
        except (OSError,subprocess.SubprocessError):
            if old: core.atomic_write(path,old)
            else: path.unlink(missing_ok=True)
            if old:
                try: _launch('bootstrap',domain,str(path))
                except (OSError,subprocess.SubprocessError): pass
            raise core.WsError('Daily registration failed; prior file restored. Inspect launchctl before retrying.')
    return {'activated':True,'path':str(path),'time':at,'publishes':False}
