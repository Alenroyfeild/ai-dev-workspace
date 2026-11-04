"""Client transcript adapters; only conversational text and tool-use presence."""
import json
import datetime
import os
import re
import stat
from pathlib import Path


def unsafe(path):
    try: info = Path(path).lstat()
    except FileNotFoundError: return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 1024)


def codex_session(session_id):
    """One regular transcript under this client's sessions directory; never accept a cached path."""
    if not isinstance(session_id, str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', session_id): return None
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').absolute()
    base = home / 'sessions'
    if unsafe(home) or unsafe(base): return None
    matches = []
    for directory, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = [name for name in dirs if not unsafe(Path(directory) / name)]
        for name in files:
            if name.endswith(session_id + '.jsonl'):
                path = Path(directory) / name
                if unsafe(path) or not path.resolve().is_relative_to(base.resolve()): return None
                matches.append(path)
                if len(matches) > 1: return None
    if len(matches) != 1: return None
    path = matches[0]; before = path.stat(); limit = 50 * 1024 * 1024
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit: return None
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        opened = os.fstat(stream.fileno()); data = stream.read(limit + 1)
    after = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if identity(before) != identity(opened) or identity(before) != identity(after) or len(data) > limit: return None
    if any(unsafe(p) for p in (path, *path.parents) if p == home or home in p.parents): return None
    entries = [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]
    if not entries or not all(isinstance(e, dict) for e in entries): return None
    header = entries[0]
    if header.get('type') != 'session_meta' or header.get('payload', {}).get('id') != session_id: return None
    stamp = datetime.datetime.fromisoformat(header['payload']['timestamp'].replace('Z', '+00:00'))
    if stamp.tzinfo is None: return None
    return path, data, stamp


def records(stream, client):
    if client == 'gemini':
        text = stream.read()
        try: entries = json.loads(text)['messages']
        except (ValueError, TypeError, KeyError):
            entries = []
            for line in text.splitlines():
                try: entries.append(json.loads(line))
                except ValueError: continue
        messages = {}
        for entry in entries:
            if not isinstance(entry, dict): continue
            if isinstance(entry.get('$set'), dict) and 'messages' in entry['$set']:
                messages = {m['id']: m for m in entry['$set']['messages'] if m.get('type') in ('user', 'gemini')}
            elif '$rewindTo' in entry:
                keys = list(messages); key = entry['$rewindTo']
                for key in keys[keys.index(key) if key in keys else 0:]: messages.pop(key)
            elif '$patch' in entry:
                patch = entry['$patch']
                for change in patch.get('updates', [patch]):
                    if change.get('id') in messages and 'content' in change: messages[change['id']]['content'] = change['content']
                for key in patch.get('removeIds', []): messages.pop(key, None)
                if 'orderIds' in patch:
                    order = [k for k in messages if k not in patch['orderIds']] + patch['orderIds']
                    messages = {k: messages[k] for k in order if k in messages}
            elif entry.get('type') in ('user', 'gemini'):
                messages[entry.get('id', str(len(messages)))] = entry
        entries = list(messages.values())
    else:
        entries = []
        for line in stream:
            try: entries.append(json.loads(line))
            except ValueError: continue
    vscode_known = False
    for entry in entries:
        if not isinstance(entry, dict): continue
        if client == 'vscode':
            data = entry.get('data')
            if not isinstance(data, dict): continue
            if entry.get('type') == 'session.start':
                vscode_known = type(data.get('version')) is int and data['version'] == 1 and data.get('producer') == 'copilot-agent'
                continue
            if not vscode_known: continue  # The upstream transcript format is not a stable hook API.
            if entry.get('type') == 'tool.execution_start' and isinstance(data.get('toolName'), str) and data['toolName']:
                yield {'type': 'assistant', 'message': {'content': [{'type': 'tool_use'}]}}
            elif entry.get('type') in ('user.message', 'assistant.message'):
                blocks = [{'type': 'text', 'text': data['content']}] if isinstance(data.get('content'), str) else []
                requests = data.get('toolRequests')
                if entry['type'] == 'assistant.message' and isinstance(requests, list) and any(isinstance(r, dict) and isinstance(r.get('name'), str) and r['name'] for r in requests):
                    blocks.append({'type': 'tool_use'})
                yield {'type': 'user' if entry['type'] == 'user.message' else 'assistant', 'message': {'content': blocks}}
        elif client == 'codex' and entry.get('type') == 'response_item':
            item = entry.get('payload', {})
            if item.get('type') in ('function_call', 'custom_tool_call') and isinstance(item.get('name'), str):
                yield {'type': 'assistant', 'message': {'content': [{'type': 'tool_use'}]}}
            elif item.get('type') == 'message' and item.get('role') in ('user', 'assistant') and item.get('channel') != 'analysis':
                kinds = item.get('internal_chat_message_metadata_passthrough', {}).get('content_item_kinds')
                content = [{'type': 'text', 'text': part['text']} for i, part in enumerate(item.get('content', []))
                           if isinstance(part, dict) and part.get('type') in ('input_text', 'output_text') and isinstance(part.get('text'), str)
                           and (item['role'] != 'user' or not kinds or i < len(kinds) and kinds[i] == 'user.text')]
                yield {'type': item['role'], 'message': {'content': content}}
        elif client == 'gemini':
            content = entry.get('content', '')
            # Only plain text parts: tool calls/results (functionCall, functionResponse) and typed non-text blocks stay out.
            text = content if isinstance(content, str) else ' '.join(
                p if isinstance(p, str) else p.get('text', '') for p in content
                if isinstance(p, str) or isinstance(p, dict) and isinstance(p.get('text'), str)
                and not ({'functionCall', 'functionResponse'} & set(p)) and p.get('type', 'text') == 'text')
            blocks = [{'type': 'text', 'text': text}]
            calls = entry.get('toolCalls')
            if isinstance(calls, list) and any(isinstance(c, dict) and isinstance(c.get('name'), str) for c in calls): blocks.append({'type': 'tool_use'})
            yield {'type': 'assistant' if entry.get('type') == 'gemini' else 'user', 'timestamp': entry.get('timestamp'), 'message': {'content': blocks}}
        else:
            yield dict(entry, type=entry.get('type', entry.get('role')))  # Cursor and Codex chat transcripts are Claude-shaped.
