#!/usr/bin/env python3
"""MCP server (stdio, newline-delimited JSON-RPC 2.0) exposing the workspace to any MCP client.

Run: python3 mcp/server.py --root <workspace>   (or set WS_ROOT). No dependencies.
"""
import argparse
import json
import math
import sys
from pathlib import Path

kit = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(kit.parent if (kit / 'core.py').is_file() else kit))
from ws import core, assist, orchestration  # noqa: E402

PROTOCOL = '2025-06-18'


def S(**props):
    required = [k for k, v in props.items() if not v.pop('optional', False)]
    return {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}


def string(desc, optional=False):
    return {'type': 'string', **({'description': desc} if desc else {}), 'optional': optional}


TOOLS = {
    'route': ('Resolve role/model and CLI availability; no fallback or credential reads.', S(role=string('', True)), lambda r, a: orchestration.route(r, a.get('role', 'lead'))),
    'delegate': ('Prepare unverified bounded work; never execute.', S(task=string(''), role=string('')), lambda r, a: orchestration.delegate(r, a['task'], a['role'])),
    'assist': ('Up to two local suggestions; ask before applying. No installs/config edits.', S(), lambda r, a: assist.suggestions(r)),
    'import_usage': ('Import Codeburn usage; skip ambiguous matches and duplicates.',
                     S(since=string('YYYY-MM-DD', True), task=string('', True)), lambda r, a: core.import_codeburn(r, a.get('since'), a.get('task'))),
    'search_sessions': ('Search Claude/Codex transcripts; snippets are redacted.',
                        S(query=string('')), lambda r, a: core.session_search(a['query'])),
    'codebase_map': ('Map the configured or supplied repo.',
                     S(repo=string('', True)), lambda r, a: core.codebase_map(r, a.get('repo'))),
    'brief': ('Show local task memory.', S(), lambda r, a: core.brief(r)),
    'nudge': ('Remind claims stale 30+ min.', S(), lambda r, a: core.nudge(r)),
    'connect_client': ('Write project config; Codex global config is preview-only.',
                       S(client={'type': 'string', 'enum': ['claude', 'codex', 'cursor']}),
                       lambda r, a: core.connect(r, a['client'])),
    'find_task': ('Find tasks by ticket, branch or title; start sessions here.',
                  S(ref=string('')),
                  lambda r, a: core.task_find(r, a['ref'])),
    'read_task': ('Read a task; select sections to reduce context.',
                  S(id=string(''), sections={'type': 'array', 'items': {'type': 'string'}, 'optional': True}),
                  lambda r, a: core.task_read(r, a['id'], a.get('sections'))),
    'new_task': ('Create a task.',
                 S(id=string(''), title=string(''), objective=string('', True), branch=string('', True)),
                 lambda r, a: core.task_new(r, a['id'], a['title'], a.get('objective', ''), a.get('branch', ''))),
    'claim_task': ('Claim before edits; returns checkpoint/release token.',
                   S(id=string(''), worker=string('')),
                   lambda r, a: core.claim(r, a['id'], a['worker'])),
    'release_task': ('Release a claim.', S(id=string(''), worker=string(''), token=string('')),
                     lambda r, a: core.release(r, a['id'], a['worker'], a['token'])),
    'checkpoint': ('Save status, exact next action and section updates.',
                   S(id=string(''), status={'type': 'string', 'enum': list(core.STATUSES)},
                     next=string(''), worker=string('', True), token=string('', True),
                     expected_sha=string('Rejects stale writes', True),
                     notes={'type': 'object', 'additionalProperties': {'type': 'string'}, 'optional': True}),
                   lambda r, a: core.checkpoint(r, a['id'], a['status'], a['next'], a.get('expected_sha'),
                                                a.get('worker'), a.get('token'), a.get('notes'))),
    'search_vault': ('Ranked notes search; returns path:line snippets.',
                     S(query=string('')), lambda r, a: core.search(r, a['query'])),
    'search_lessons': ('Find matching lessons; check before risky work.',
                       S(query=string('', True)), lambda r, a: core.lesson_search(r, a.get('query', ''))),
    'add_lesson': ('Record a lesson.', S(text=string('')),
                   lambda r, a: core.lesson_add(r, a['text'])),
    'add_feedback': ('Record idea, bug, friction or praise.',
                     S(text=string(''), kind=string('', True)),
                     lambda r, a: core.feedback_add(r, a['text'], a.get('kind', 'idea'), 'assistant')),
    'digest_file': ('Summarize JSON shape; deduplicate log problems.',
                    S(path=string('')), lambda r, a: core.digest_file(a['path'])),
    'log_step': ('Record orchestration step, timing and token data for reports.',
                 S(task=string(''), step=string(''), provider=string(''),
                   model=string('', True), tokens_in={'type': 'integer', 'optional': True},
                   tokens_out={'type': 'integer', 'optional': True}, seconds={'type': 'number', 'optional': True},
                   result=string('ok|failed|rejected|accepted|skipped', True), note=string('', True),
                   worker_role=string('', True), effort=string('', True),
                   checks={'type': 'array', 'items': {'type': 'string'}, 'optional': True},
                   files={'type': 'integer', 'optional': True}, findings={'type': 'integer', 'optional': True},
                   verdict={'type': 'string', 'enum': ['accepted', 'changes', 'rejected'], 'optional': True}),
                 lambda r, a: core.run_log(r, a['task'], a['step'], a['provider'], a.get('model', ''), a.get('tokens_in', 0),
                                           a.get('tokens_out', 0), a.get('seconds', 0), a.get('result', 'ok'), a.get('note', ''),
                                           a.get('worker_role', ''), a.get('effort', ''), a.get('checks', []),
                                           a.get('files'), a.get('verdict', ''), a.get('findings'))),
    'trace': ('Read-only orchestration timeline and token totals.',
              S(task=string('')), lambda r, a: core.trace(r, a['task'])),
    'notices': ('At session start, present notices; run suggestions only with approval.',
                S(), lambda r, a: core.notices(r)),
    'status': ('Show workspace overview and run costs.',
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
                  'serverInfo': {'name': 'ai-dev-workspace', 'version': core.kit_meta()['version']}}
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
