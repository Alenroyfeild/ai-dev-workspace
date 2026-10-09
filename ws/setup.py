"""Assistant selection; read-only detection and explicit project configuration."""
import json
from pathlib import Path
from . import core, orchestration, upgrade


def detect():
    providers = json.loads(orchestration.routing_template())['_ws_managed']['providers']
    return [dict(assistant=name, cli=data['cli'], cli_available=bool(core.shutil.which(data['cli'])),
                 apps=[app for app in data.get('apps', []) if core._has_app(app)])
            for name, data in providers.items()]


def selection_json(text, values):
    """Replace selected top-level values, keeping every other byte intact."""
    decoder = json.JSONDecoder(); data = json.loads(text)
    if not isinstance(data, dict): raise core.WsError('Routing configuration must be an object.')
    def skip(at):
        while at < len(text) and text[at].isspace(): at += 1
        return at
    at = skip(0) + 1; edits = []; seen = set()
    while text[skip(at)] != '}':
        key, at = decoder.raw_decode(text, skip(at))
        if key in seen: raise core.WsError('Ambiguous duplicate routing key.')
        seen.add(key); start = skip(skip(at) + 1); _, at = decoder.raw_decode(text, start)
        if key in values: edits.append((start, at, json.dumps(values[key], ensure_ascii=False)))
        at = skip(at)
        if text[at] == ',': at += 1
    close = skip(at)
    missing = {key: value for key, value in values.items() if key not in seen}
    if missing:
        addition = (',' if seen else '') + '\n  ' + ',\n  '.join(json.dumps(key) + ': ' + json.dumps(value) for key, value in missing.items()) + '\n'
        edits.append((close, close, addition))
    for start, end, replacement in sorted(edits, reverse=True): text = text[:start] + replacement + text[end:]
    return text


def configure(root, assistants, preset=None):
    if not isinstance(assistants, list) or not assistants or any(not isinstance(name, str) for name in assistants):
        raise core.WsError('Choose assistants with --assistants a,b.')
    preset = preset or (assistants[0] + '-only' if len(assistants) == 1 and assistants[0] != 'ollama' else
                        'claude+codex' if set(assistants) == {'claude', 'codex'} else 'mixed')
    if preset == 'claude+codex': assistants = ['claude', 'codex']
    candidate = orchestration.routing_template(preset, assistants)
    path = root / 'routing.json'
    for target in (path, root / 'workspace.json', root / '.ws', root / '.ws/backups'):
        if target.is_symlink(): raise core.WsError('Setup refuses symlinked configuration/backups.')
    with core.lock(root):
        original = core.read_text(path, [root]) if path.exists() else None
        if original is not None:
            existing = json.loads(original)
            if not isinstance(existing, dict) or not isinstance(existing.get('role_overrides', {}), dict):
                raise core.WsError('Invalid routing overrides; review routing.json first.')
            for override in existing.get('role_overrides', {}).values():
                if not isinstance(override, dict) or not isinstance(override.get('preference', []), list):
                    raise core.WsError('Invalid routing override; review routing.json first.')
                if (override.get('provider') and override['provider'] not in assistants or
                        any(name not in assistants for name in override.get('preference', []))):
                    raise core.WsError('Existing role override references an unselected assistant; review routing.json first.')
            merged = upgrade.routing(original, candidate)
            if merged is None: raise core.WsError('Unmanaged routing file; review ws upgrade proposals first.')
            desired = json.loads(candidate)
            candidate = selection_json(merged, {name: desired[name] for name in ('preset', 'assistants', 'delegation_mode')})
        cfg = core.config(root); updated = dict(cfg, routing_preset=preset, assistants=assistants)
        backup = root / '.ws/backups' / (core.now().replace(':', '').replace('+', '-') + '-' + core.uuid.uuid4().hex[:6])
        for source, text in ((path, original), (root / 'workspace.json', core.read_text(root / 'workspace.json', [root]))):
            if text is not None: core.atomic_write(backup / source.name, text)
        core.atomic_write(path, candidate)
        core.atomic_write(root / 'workspace.json', json.dumps(updated, indent=2) + '\n')
    connections = []
    for assistant in assistants:
        if assistant == 'ollama':
            connections.append(dict(client=assistant, connected=False, note='Local model configuration only; no client hook adapter.'))
            continue
        try: result = core.connect(root, assistant, skills=False, verify=False)
        except core.WsError as exc: result = dict(client=assistant, connected=False, note=str(exc))
        if assistant == 'codex' and not result.get('connected'):
            result['note'] = 'Project hooks/skills configured; MCP preview only. Review ws connect codex --write if you want global MCP configuration.'
        if assistant == 'copilot': result['note'] = 'Copilot CLI: project rules plus MCP only; no lifecycle capture configured.'
        connections.append(result)
    return dict(preset=preset, assistants=assistants, backup=str(backup), connections=connections,
                note='Restart and trust the workspace in each selected client. Detection does not verify login/model access.')
