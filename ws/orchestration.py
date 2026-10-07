"""Explicit bindings and bounded delegation; availability is PATH-only."""
import json
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path
from . import core


def routing_template():
    return (core.KIT / 'template/routing.json').read_text().replace('{{kit_version}}', core.kit_meta()['version'])


def route(root, role='lead'):
    if role not in ('lead', 'planner', 'worker', 'explorer', 'reviewer', 'local'): raise core.WsError('Unknown orchestration role.')
    try:
        cfg = json.loads((root / 'routing.json').read_text()); defaults = cfg['_ws_managed']
        definition = defaults['roles'][role]; override = cfg.get('role_overrides', {}).get(role, {})
        # An explicit provider override pins one provider; otherwise the first available in the preference order wins,
        # and every skipped provider is reported (an explicit, visible fallback, never a silent one).
        preference = [override['provider']] if override.get('provider') else override.get('preference', definition['preference'])
        skipped, chosen = [], None
        for provider in preference:
            if provider not in ('claude', 'codex', 'ollama'): raise ValueError()
            settings = defaults['providers'][provider]
            tier = settings['tiers'][override.get('tier', definition['tier'])]
            family = override.get('family', tier['family']); effort = override.get('effort', tier['effort'])
            model = override['model'] if 'model' in override else settings['models'].get(family)
            if effort not in ('low', 'medium', 'high', 'not_applicable'): raise ValueError()
            if model is not None and (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,120}', model)): raise ValueError()
            executable = core.shutil.which(provider)
            candidate = dict(role=role, provider=provider, family=family, model=model, effort=effort, executable=executable)
            if executable and model:
                chosen = candidate; break
            skipped.append({'provider': provider, 'reason': 'CLI not on PATH' if not executable else 'no model configured'})
            chosen = chosen or candidate
        available = bool(chosen['executable'] and chosen['model'])
        return dict(chosen, available=available, preference=preference, skipped=skipped,
                    timeout_seconds=int(cfg.get('timeout_seconds', 600)),
                    reason='' if available else 'No provider in the preference order is available; configure routing.json.')
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise core.WsError('Invalid or missing routing.json binding; run ws upgrade and review routing configuration.')


def _worker_output(provider, stdout):
    tokens_in = tokens_out = 0
    known = False
    messages = []
    if provider == 'codex':
        turns = unknown = False
        for line in stdout.splitlines():
            try: event = json.loads(line)
            except ValueError: continue
            if not isinstance(event, dict): continue
            item = event.get('item', {})
            if not isinstance(item, dict): item = {}
            if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                if isinstance(item.get('text'), str): messages.append(item['text'])
            if event.get('type') == 'turn.completed':
                turns = True
                usage = event.get('usage', {})
                if not isinstance(usage, dict): usage = {}
                incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
                if type(incoming) is int and incoming >= 0 and type(outgoing) is int and outgoing >= 0:
                    tokens_in += incoming; tokens_out += outgoing
                else: unknown = True
        known = turns and not unknown
        if not known: tokens_in = tokens_out = 0
    elif provider == 'claude':
        try: payload = json.loads(stdout)
        except ValueError: payload = {}
        if not isinstance(payload, dict): payload = {}
        if isinstance(payload.get('result'), str): messages.append(payload['result'])
        usage = payload.get('usage', {})
        if not isinstance(usage, dict): usage = {}
        incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
        if type(incoming) is int and incoming >= 0 and type(outgoing) is int and outgoing >= 0:
            tokens_in, tokens_out, known = incoming, outgoing, True
    return '\n'.join(messages) or stdout, tokens_in, tokens_out, known


def delegate(root, task_id, role, run=False):
    if run and role not in ('explorer', 'reviewer'):
        raise core.WsError('Only explorer/reviewer may run; write roles are preparation-only.')
    binding = route(root, role)
    if not binding['available']: raise core.WsError(binding['reason'] + ' Provider: ' + binding['provider'])
    if run and binding['provider'] == 'ollama': raise core.WsError('Ollama is preparation-only; ws never pulls models.')
    task = core.task_read(root, task_id, ['Objective', 'Next action', 'Blockers', 'Evidence'])
    meta = task['meta']; worker, token = core._claim_defaults(root, task_id, None, None)
    if run and meta.get('claimed_by') and (worker != meta['claimed_by'] or token != meta.get('claim_token')):
        raise core.WsError('Task claimed elsewhere; cannot append worker evidence.')
    paths = [Path(meta.get('repo') or next(iter(core.config(root).get('repos', [])), str(root))).expanduser().resolve()]
    if not paths[0].is_dir(): raise core.WsError('Task repository is not a directory.')
    body = '# Bounded delegation (UNVERIFIED)\nLead decides and reviews; workers do bounded work. Read only allowed paths; no credentials or external services.\n'
    for section, limit in (('Objective', 80), ('Next action', 60), ('Blockers', 30), ('Evidence', 100)):
        body += f'\n## {section}\n' + ' '.join(core.redact(task['sections'][section]).split()[:limit]) + '\n'
    body += '\n## Allowed paths\n' + '\n'.join(map(str, paths)) + '\n\n## Output contract\nUNVERIFIED findings with file:line and checks actually performed; report blockers. Do not implement, commit, accept or change task memory.\n'
    if len(body.split()) > 400: raise core.WsError('Brief scope exceeds 400 words; shorten repository paths.')
    identifier = task_id + '-' + role + '-' + core.uuid.uuid4().hex[:8]
    if (root / '.ws').is_symlink() or (root / '.ws/briefs').is_symlink(): raise core.WsError('Delegation refuses symlinked brief directories.')
    brief = root / '.ws/briefs' / (identifier + '.md'); output = brief.with_suffix('.out.md')
    exe, model, effort = binding['executable'], binding['model'], binding['effort']
    if binding['provider'] == 'codex':
        command = [exe, 'exec', '--json', '-s', 'read-only', '--ephemeral', '--ignore-user-config', '--disable', 'hooks', '--disable', 'apps', '--disable', 'plugins',
                   '-c', 'approval_policy="never"', '-m', model, '-c', 'model_reasoning_effort=' + json.dumps(effort), '--skip-git-repo-check', '-C', str(paths[0]), '-']
    elif binding['provider'] == 'claude':
        # Not --bare: it accepts only an API key, so subscription logins would fail.
        command = [exe, '-p', '--output-format', 'json', '--setting-sources', 'project', '--model', model, '--effort', effort, '--tools', 'Read,Glob,Grep', '--allowedTools', 'Read,Glob,Grep',
                   '--permission-mode', 'dontAsk', '--mcp-config', '{"mcpServers":{}}', '--strict-mcp-config', '--no-session-persistence']
    else: command = [exe, 'run', model]
    with core.lock(root): core.atomic_write(brief, core.redact(body))
    result = dict(binding=binding, brief=str(brief), output=str(output), command=shlex.join(command) + ' < ' + shlex.quote(str(brief)) + ' > ' + shlex.quote(str(output)))
    if not run: return result
    started = time.monotonic(); code = 1; rendered = ''
    try:
        process = subprocess.Popen(command, cwd=paths[0], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try: stdout, stderr = process.communicate(body, timeout=binding['timeout_seconds']); code = process.returncode
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); stdout, stderr = process.communicate(); stderr += f"\nWorker timed out after {binding['timeout_seconds']} seconds."
        rendered, tokens_in, tokens_out, usage_known = _worker_output(binding['provider'], stdout)
        rendered = core.redact(rendered + ('\n' + stderr[-1000:] if code else ''))[:24000]
    except OSError:
        rendered = 'Selected provider could not launch; no fallback.'
        tokens_in = tokens_out = 0; usage_known = False
    with core.lock(root):
        core.atomic_write(output, 'UNVERIFIED worker output\n' + rendered)
        path = core.task_path(root, task_id); text = path.read_text(); current = core.parse_meta(text)
        if current.get('claimed_by') and (worker != current['claimed_by'] or token != current.get('claim_token')):
            raise core.WsError('Claim changed during delegation; output saved, task evidence not changed.')
        match = re.search(r'^## Evidence[^\n]*\n.*?(?=^## |\Z)', text, re.M | re.S)
        if not match: raise core.WsError('Task has no Evidence section; output saved.')
        summary = f'\nDelegated {role} ({model}, {effort}), exit {code}, unverified: ' + ' '.join(rendered.split()[:45]) + '\n'
        core.atomic_write(path, text[:match.end()] + summary + text[match.end():])
    core.run_log(root, task_id, 'delegate ' + role, binding['provider'], model, seconds=time.monotonic()-started,
                 tokens_in=tokens_in, tokens_out=tokens_out, result='ok' if code == 0 else 'failed', worker_role=role,
                 effort=effort, note='Worker output unverified; lead must review.' + ('' if usage_known else ' usage unavailable.'))
    return dict(result, exit_code=code)
