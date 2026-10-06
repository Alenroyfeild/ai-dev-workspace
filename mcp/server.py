#!/usr/bin/env python3
"""MCP server (stdio, newline-delimited JSON-RPC 2.0) exposing the workspace to any MCP client.

Run: python3 mcp/server.py --root <workspace>   (or set WS_ROOT). No dependencies.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws import core  # noqa: E402

PROTOCOL = '2025-06-18'


def S(**props):
    required = [k for k, v in props.items() if not v.pop('optional', False)]
    return {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}


def string(desc, optional=False):
    return {'type': 'string', 'description': desc, 'optional': optional}


TOOLS = {
    'search_sessions': ('Search local Claude Code and Codex transcripts; returned snippets are redacted.',
                        S(query=string('words or phrase to find')), lambda r, a: core.session_search(a['query'])),
    'codebase_map': ('Write a compact codebase map for the configured or supplied repository.',
                     S(repo=string('repository path', True)), lambda r, a: core.codebase_map(r, a.get('repo'))),
    'brief': ('Short local task memory: next action, blockers and matching lessons.', S(), lambda r, a: core.brief(r)),
    'nudge': ('Checkpoint reminder for a claim without a checkpoint for 30 minutes.', S(), lambda r, a: core.nudge(r)),
    'connect_client': ('Write a project MCP config, or preview the Codex global config without changing it.',
                       S(client={'type': 'string', 'enum': ['claude', 'codex', 'cursor']}),
                       lambda r, a: core.connect(r, a['client'])),
    'find_task': ('Find task records by ticket key, branch or title words. Start every session with this.',
                  S(ref=string('ticket key, branch name or title words')),
                  lambda r, a: core.task_find(r, a['ref'])),
    'read_task': ('Read a task record. Pass sections to read only those (cheaper), e.g. ["Next action","Blockers","Handoff"].',
                  S(id=string('task ID'), sections={'type': 'array', 'items': {'type': 'string'}, 'optional': True}),
                  lambda r, a: core.task_read(r, a['id'], a.get('sections'))),
    'new_task': ('Create a task record from the template.',
                 S(id=string('task ID, e.g. JIRA-123'), title=string('short title'),
                   objective=string('what and why', True), branch=string('git branch', True)),
                 lambda r, a: core.task_new(r, a['id'], a['title'], a.get('objective', ''), a.get('branch', ''))),
    'claim_task': ('Claim a task before changing anything. Returns a token needed to checkpoint or release.',
                   S(id=string('task ID'), worker=string('short worker label, e.g. claude-main')),
                   lambda r, a: core.claim(r, a['id'], a['worker'])),
    'release_task': ('Release your claim.', S(id=string('task ID'), worker=string('worker'), token=string('claim token')),
                     lambda r, a: core.release(r, a['id'], a['worker'], a['token'])),
    'checkpoint': ('Save progress: status, exact next action, optional section updates (Evidence, Findings, Checks, Blockers, Handoff, Do not redo, Failures, Risks).',
                   S(id=string('task ID'), status={'type': 'string', 'enum': list(core.STATUSES)},
                     next=string('exact next action'), worker=string('claim worker', True), token=string('claim token', True),
                     expected_sha=string('sha from read_task, rejects stale writes', True),
                     notes={'type': 'object', 'additionalProperties': {'type': 'string'}, 'optional': True}),
                   lambda r, a: core.checkpoint(r, a['id'], a['status'], a['next'], a.get('expected_sha'),
                                                a.get('worker'), a.get('token'), a.get('notes'))),
    'search_vault': ('Ranked search over product, project, runbook and analysis notes. Returns path:line snippets, not whole files.',
                     S(query=string('words to look for')), lambda r, a: core.search(r, a['query'])),
    'search_lessons': ('Lessons learned (mistake → rule) matching the words. Check before risky work.',
                       S(query=string('words', True)), lambda r, a: core.lesson_search(r, a.get('query', ''))),
    'add_lesson': ('Record a lesson: what happened → rule.', S(text=string('lesson')),
                   lambda r, a: core.lesson_add(r, a['text'])),
    'add_feedback': ('Record user feedback about the workspace (idea, bug, friction, praise).',
                     S(text=string('feedback'), kind=string('idea|bug|friction|praise', True)),
                     lambda r, a: core.feedback_add(r, a['text'], a.get('kind', 'idea'), 'assistant')),
    'digest_file': ('Summarise a big log or JSON file deterministically (problem lines deduplicated, or JSON shape). Read this instead of the file.',
                    S(path=string('absolute file path')), lambda r, a: core.digest_file(a['path'])),
    'log_step': ('Record one orchestration step (who did it, model, tokens, seconds, result) for later cost/quality reports.',
                 S(task=string('task ID'), step=string('step name'), provider=string('claude|codex|ollama|...'),
                   model=string('model id', True), tokens_in={'type': 'integer', 'optional': True},
                   tokens_out={'type': 'integer', 'optional': True}, seconds={'type': 'number', 'optional': True},
                   result=string('ok|failed|rejected|accepted|skipped', True), note=string('short note', True)),
                 lambda r, a: core.run_log(r, a['task'], a['step'], a['provider'], a.get('model', ''), a.get('tokens_in', 0),
                                           a.get('tokens_out', 0), a.get('seconds', 0), a.get('result', 'ok'), a.get('note', ''))),
    'notices': ('Call once at session start. Returns short notices (new release, fixed issue, unshared feedback), each with a suggested command. Tell the user in one line each and run the command only if they say yes.',
                S(), lambda r, a: core.notices(r)),
    'status': ('Workspace overview: task counts, claims, blocked work, open feedback, run costs.',
               S(), lambda r, a: core.status(r)),
}


def rpc_error(mid, code, message):
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}


def validate_input(value, schema, field='arguments'):
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'integer': type(value) is int,
             'number': type(value) is int or (type(value) is float and math.isfinite(value))}
    if kind and not valid.get(kind, False):
        raise ValueError(f'{field} must be {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{field} is not an allowed value')
    if kind == 'object':
        props = schema.get('properties', {})
        if any(key not in value for key in schema.get('required', [])):
            raise ValueError(f'{field} is missing required fields')
        extra = schema.get('additionalProperties', True)
        for key, item in value.items():
            if key in props:
                validate_input(item, props[key], f'{field}.{key}')
            elif extra is False:
                raise ValueError(f'{field} has unknown fields')
            elif isinstance(extra, dict):
                validate_input(item, extra, f'{field}.{key}')
    elif kind == 'array':
        for item in value:
            validate_input(item, schema['items'], field + '[]')


def handle(root, msg):
    if (not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0'
            or not isinstance(msg.get('method'), str)
            or ('id' in msg and msg['id'] is not None and type(msg['id']) not in (int, str))):
        return rpc_error(None, -32600, 'Invalid request')
    method, mid = msg['method'], msg.get('id')
    if 'id' not in msg:
        return None  # notification
    params = msg.get('params', {})
    if not isinstance(params, dict):
        return rpc_error(mid, -32602, 'Params must be an object')
    if method == 'initialize':
        try:
            validate_input(params, S(protocolVersion=string('version', True),
                                     capabilities={'type': 'object', 'optional': True},
                                     clientInfo={'type': 'object', 'optional': True}))
        except ValueError as exc:
            return rpc_error(mid, -32602, str(exc))
        result = {'protocolVersion': params.get('protocolVersion', PROTOCOL),
                  'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'ai-dev-workspace', 'version': '0.1.0'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': n, 'description': d, 'inputSchema': s} for n, (d, s, _) in TOOLS.items()]}
    elif method == 'tools/call':
        name = params.get('name')
        args = params.get('arguments', {})
        if not isinstance(name, str):
            return rpc_error(mid, -32602, 'Tool name must be a string')
        if name not in TOOLS:
            return rpc_error(mid, -32602, f'Unknown tool {name}')
        try:
            validate_input(args, TOOLS[name][1])
        except ValueError as exc:
            return rpc_error(mid, -32602, str(exc))
        try:
            value = TOOLS[name][2](root, args)
            result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False, indent=1)}], 'isError': False}
        except (core.WsError, KeyError, OSError, ValueError, TypeError) as exc:
            result = {'content': [{'type': 'text', 'text': f'{type(exc).__name__}: {exc}'}], 'isError': True}
    elif method == 'ping':
        result = {}
    else:
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'Method not found: {method}'}}
    return {'jsonrpc': '2.0', 'id': mid, 'result': result}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', help='workspace directory (default: WS_ROOT or current directory)')
    root = core.find_root(p.parse_args().root)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(root, json.loads(line))
        except json.JSONDecodeError:
            reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
