"""Client transcript adapters; only conversational text and tool-use presence."""
import json


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
    for entry in entries:
        if not isinstance(entry, dict): continue
        if client == 'codex' and entry.get('type') == 'response_item':
            item = entry.get('payload', {})
            if item.get('type') in ('function_call', 'custom_tool_call'):
                yield {'type': 'assistant', 'message': {'content': [{'type': 'tool_use'}]}}
            elif item.get('type') == 'message' and item.get('role') in ('user', 'assistant') and item.get('channel') != 'analysis':
                kinds = item.get('internal_chat_message_metadata_passthrough', {}).get('content_item_kinds')
                content = [{'type': 'text', 'text': part['text']} for i, part in enumerate(item.get('content', []))
                           if isinstance(part, dict) and part.get('type') in ('input_text', 'output_text') and isinstance(part.get('text'), str)
                           and (item['role'] != 'user' or not kinds or i < len(kinds) and kinds[i] == 'user.text')]
                yield {'type': item['role'], 'message': {'content': content}}
        elif client == 'gemini':
            content = entry.get('content', '')
            text = content if isinstance(content, str) else ' '.join(p if isinstance(p, str) else p.get('text', '') for p in content if isinstance(p, (str, dict)))
            blocks = [{'type': 'text', 'text': text}]
            if entry.get('toolCalls'): blocks.append({'type': 'tool_use'})
            yield {'type': 'assistant' if entry.get('type') == 'gemini' else 'user', 'timestamp': entry.get('timestamp'), 'message': {'content': blocks}}
        else:
            yield dict(entry, type=entry.get('type', entry.get('role')))  # Cursor and Codex chat transcripts are Claude-shaped.
