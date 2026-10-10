"""Assistant selection; read-only detection and explicit project configuration."""
import json
import difflib
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


def configure(root, assistants, preset=None, dry_run=False):
    if not isinstance(assistants, list) or not assistants or any(not isinstance(name, str) for name in assistants):
        raise core.WsError('Choose assistants with --assistants a,b.')
    assistants = list(dict.fromkeys('copilot' if name == 'vscode' else name for name in assistants))
    preset = preset or (assistants[0] + '-only' if len(assistants) == 1 and assistants[0] != 'ollama' else
                        'claude+codex' if set(assistants) == {'claude', 'codex'} else 'mixed')
    if preset == 'claude+codex': assistants = ['claude', 'codex']
    candidate = orchestration.routing_template(preset, assistants)
    path = root / 'routing.json'
    for target in (path, root / 'workspace.json', root / '.ws', root / '.ws/backups'):
        if target.is_symlink(): raise core.WsError('Setup refuses symlinked configuration/backups.')
    clients = ['vscode' if name == 'copilot' else name for name in assistants]
    config_paths = ['routing.json', 'workspace.json']
    hook_paths = {'codex': '.codex/hooks.json', 'cursor': '.cursor/hooks.json', 'vscode': '.github/hooks/ai-dev-workspace.json'}
    for client in clients:
        if client in core.MCP_LOCATIONS: config_paths.append(core.MCP_LOCATIONS[client][0])
        if client in hook_paths: config_paths.append(hook_paths[client])
    for relative in config_paths:
        target = root / relative
        if any(p.is_symlink() for p in (target, *target.parents) if p == root or root in p.parents):
            raise core.WsError('Setup refuses symlinked client configuration: ' + relative)
    note = ('Restart each selected client; trust this project and approve its MCP server/hooks. '
            'Codex project hooks require trust; global MCP stays preview-only. Detection does not verify login/model access.')
    with (core.contextlib.nullcontext() if dry_run else core.lock(root)):
        original = path.read_bytes().decode('utf-8') if path.exists() else None
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
        metadata = (root / 'workspace.json').read_bytes().decode('utf-8')
        if dry_run:
            changes = [dict(path=name, diff=core.redact(''.join(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), fromfile=name, tofile=name))))
                for name, old, new in (('routing.json', original or '', candidate),
                                       ('workspace.json', metadata, json.dumps(updated, indent=2) + '\n')) if old != new]
            return dict(dry_run=True, preset=preset, assistants=assistants, config_paths=config_paths,
                        changes=changes, clients=clients, note=note + ' Preview only; repeat with --apply to configure these paths.')
        backup = root / '.ws/backups' / (core.now().replace(':', '').replace('+', '-') + '-' + core.uuid.uuid4().hex[:6])
        for source, text in ((path, original), (root / 'workspace.json', metadata)):
            if text is not None: core.atomic_write(backup / source.name, text)
        core.atomic_write(path, candidate)
        core.atomic_write(root / 'workspace.json', json.dumps(updated, indent=2) + '\n')
    connections = []
    for assistant in clients:
        if assistant == 'ollama':
            connections.append(dict(client=assistant, connected=False, note='Local model configuration only; no client hook adapter.'))
            continue
        try: result = core.connect(root, assistant, skills=False, verify=False)
        except core.WsError as exc: result = dict(client=assistant, connected=False, error=True, note=str(exc))
        if assistant == 'codex' and not result.get('connected'):
            result['note'] = 'Project hooks/skills configured; MCP preview only. Review ws connect codex --write if you want global MCP configuration.'
        connections.append(result)
    partial = any(c.get('error') or c.get('hooks', {}).get('collisions') or
                  c.get('client') not in ('codex', 'ollama') and not c.get('connected') for c in connections)
    if partial: note += ' Partial setup: resolve the reported conflicts and repeat --apply; routing backups are retained.'
    return dict(dry_run=False, partial=partial, preset=preset, assistants=assistants, backup=str(backup), connections=connections,
                config_paths=config_paths, note=note)
