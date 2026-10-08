"""Private packs stay at their source path; only workspace content is installed."""
import json
import stat
from pathlib import Path
from . import core


def load(directory):
    source = Path(directory).expanduser()
    if source.is_symlink(): raise core.WsError(f'Private pack refuses symlink: {source}. Use the real folder with ws pack add --from.')
    source = source.resolve()
    try:
        for path in [source, *source.rglob('*')]:
            if path.is_symlink() or not (path.is_dir() or stat.S_ISREG(path.stat().st_mode)):
                raise core.WsError(f'Private pack refuses symlinks/non-regular files: {path}. Remove them and retry ws pack add --from.')
        manifest = json.loads((source / 'pack.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or any(not isinstance(manifest.get(k), str) or not manifest[k].strip()
                                               for k in ('name', 'version', 'kind', 'description')):
            raise ValueError('name, version, kind and description must be nonempty strings')
        name = manifest['name']
        if not core.ID_RE.fullmatch(name) or name in ('.', '..'):
            raise ValueError('name must be a safe short pack ID')
        if name in core.available_packs():
            raise ValueError('name conflicts with a bundled pack; choose a private name')
        requirements = manifest.get('requires', [])
        if not isinstance(requirements, list) or any(not isinstance(r, dict) or not (r.get('cmd') or r.get('app'))
                or any(not isinstance(r.get(k), str) for k in ('why', 'install'))
                or any(not isinstance(v, str) for k, v in r.items() if k != 'optional')
                or ('optional' in r and type(r['optional']) is not bool) for r in requirements):
            raise ValueError('requires must contain cmd/app string entries and optional booleans')
        for key in ('setup', 'selftest'):
            if key in manifest:
                path = source / manifest[key]
                if not path.is_file() or source not in path.resolve().parents:
                    raise ValueError(key + ' must name a file inside the pack')
        files = {'vault/' + str(p.relative_to(source / 'vault')): p.read_bytes()
                 for p in sorted((source / 'vault').rglob('*')) if p.is_file()}
        snippet = source / 'AGENTS.snippet.md'
        body = snippet.read_text(encoding='utf-8').replace('<kit>', str(core.KIT)) if snippet.exists() else ''
        rules = f'<!--ws:private-pack:{name}-->\n{body.rstrip()}\n<!--/ws:private-pack:{name}-->\n' if body else ''
        return source, manifest, files, rules
    except (OSError, ValueError, TypeError) as exc:
        raise core.WsError(f'Invalid private pack {source}/pack.json: {exc}. Fix the pack and retry ws pack add --from.') from exc


def safe(root, relative):
    path = root / relative
    if root.resolve() not in path.resolve().parents or any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
        raise core.WsError(f'Private pack destination is unsafe: {relative}. Remove the symlink and retry ws pack add --from.')
    return path


def add(root, directory):
    source, manifest, files, rules = load(directory)
    name = manifest['name']
    for relative in [*files, 'AGENTS.md', 'workspace.json']: safe(root, relative)
    with core.lock(root):
        cfg = core.config(root)
        local = cfg.setdefault('local_packs', {})
        if name in cfg['packs']:
            if local.get(name, {}).get('path') != str(source):
                raise core.WsError(f'Pack {name} already has another source. Run ws pack remove {name} first.')
            return {'pack': name, 'installed': True, 'next': ['ws upgrade'], 'collisions': []}
        collisions = []
        for relative, text in files.items(): core.write_preserving(root / relative, text, collisions)
        path = root / 'AGENTS.md'
        if rules: core.atomic_write(path, path.read_text() + '\n' + rules)
        local[name] = dict(path=str(source), version=manifest['version'], files={p: core.hashlib.sha256(t).hexdigest() for p, t in files.items()}, rules=rules)
        cfg['packs'].append(name)
        core.atomic_write(root / 'workspace.json', json.dumps(cfg, indent=2) + '\n')
    return {'pack': name, 'installed': True, 'collisions': collisions, 'next': ['ws upgrade to refresh this source']}


def remove(root, name):
    with core.lock(root):
        cfg = core.config(root)
        entry = cfg.get('local_packs', {}).get(name)
        if entry is None: raise core.WsError(f'No private pack {name}. Check workspace.json; ws pack remove supports private packs.')
        paths = {p: safe(root, p) for p in [*entry['files'], 'AGENTS.md', 'workspace.json']}
        kept = []
        for relative, digest in entry['files'].items():
            path = paths[relative]
            if path.is_file() and core.hashlib.sha256(path.read_bytes()).hexdigest() == digest: path.unlink()
            elif path.exists(): kept.append(relative)
        path = paths['AGENTS.md']; text = path.read_text()
        if entry['rules'] and entry['rules'] in text: core.atomic_write(path, text.replace(entry['rules'], '', 1))
        elif entry['rules']: kept.append('AGENTS.md')
        del cfg['local_packs'][name]; cfg['packs'].remove(name)
        core.atomic_write(paths['workspace.json'], json.dumps(cfg, indent=2) + '\n')
        return {'pack': name, 'removed': True, 'kept': kept}


def desired(root, cfg, content):
    owners = {}
    for name, entry in cfg.get('local_packs', {}).items():
        source, manifest, files, rules = load(entry['path'])
        if manifest['name'] != name: raise core.WsError(f'Private pack changed name: {source}/pack.json. Restore {name} and rerun ws upgrade.')
        for relative, text in files.items():
            if relative in owners: raise core.WsError(f'Private packs share {relative}. Rename the file and rerun ws upgrade.')
            content[relative] = text; owners[relative] = entry['files'].get(relative)
        entry.update(version=manifest['version'], files={**entry['files'], **{p: core.hashlib.sha256(t).hexdigest() for p, t in files.items()}})
        content['AGENTS.md'] += rules
    return owners


def merge_rules(old, merged, cfg):
    if merged is None: return None
    for entry in cfg.get('local_packs', {}).values():
        rules = load(entry['path'])[3]
        previous = entry['rules']
        if previous and previous not in old: return None
        merged = merged.replace(previous, rules, 1) if previous else merged + rules
        entry['rules'] = rules
    return merged
