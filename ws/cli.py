"""`ws` command line. Every command prints JSON or plain text and exits non-zero on error."""
import argparse
import json
import sys
from pathlib import Path

from . import core


def out(value):
    print(value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False))


def main(argv=None):
    p = argparse.ArgumentParser(prog='ws', description='AI Dev Workspace: shared memory and coordination for AI-assisted development.')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('init', help='create a workspace')
    s.add_argument('dir'); s.add_argument('--name', required=True)
    s.add_argument('--pack', action='append', default=[], help=f'domain pack: {", ".join(core.available_packs())}')
    s.add_argument('--repo', action='append', default=[], help='code checkout this workspace serves')
    sub.add_parser('packs', help='list available packs')
    s = sub.add_parser('pack', help='plug a pack into this workspace'); s.add_argument('action', choices=['add']); s.add_argument('name')
    sub.add_parser('status', help='workspace overview')
    sub.add_parser('validate', help='check task records, links and secrets')
    sub.add_parser('doctor', help='check which tools are installed')
    s = sub.add_parser('map', help='write a compact codebase map'); s.add_argument('repo', nargs='?')

    t = sub.add_parser('task', help='task records').add_subparsers(dest='action', required=True)
    s = t.add_parser('new'); s.add_argument('id'); s.add_argument('title')
    s.add_argument('--objective', default=''); s.add_argument('--branch', default=''); s.add_argument('--repo', default='')
    t.add_parser('list')
    s = t.add_parser('find'); s.add_argument('ref')
    s = t.add_parser('show'); s.add_argument('id'); s.add_argument('--section', action='append')

    s = sub.add_parser('claim'); s.add_argument('id'); s.add_argument('--worker', required=True)
    s = sub.add_parser('release'); s.add_argument('id'); s.add_argument('--worker', required=True); s.add_argument('--token', required=True)
    s = sub.add_parser('checkpoint'); s.add_argument('id'); s.add_argument('--status', required=True, choices=core.STATUSES)
    s.add_argument('--next', required=True); s.add_argument('--expected-sha'); s.add_argument('--worker'); s.add_argument('--token')
    s.add_argument('--note', action='append', default=[], metavar='SECTION=TEXT')

    s = sub.add_parser('search', help='ranked vault search (snippets, not whole files)'); s.add_argument('query')
    l = sub.add_parser('lesson').add_subparsers(dest='action', required=True)
    s = l.add_parser('add'); s.add_argument('text'); s.add_argument('--tag', action='append', default=[])
    s = l.add_parser('search'); s.add_argument('query', nargs='?', default='')
    f = sub.add_parser('feedback').add_subparsers(dest='action', required=True)
    s = f.add_parser('add'); s.add_argument('text'); s.add_argument('--kind', default='idea'); s.add_argument('--source', default='user')
    s = f.add_parser('list'); s.add_argument('--all', action='store_true')
    s = f.add_parser('submit', help='turn item N into a GitHub issue (preview first)'); s.add_argument('n', type=int); s.add_argument('--yes', action='store_true')
    s = f.add_parser('link', help='record the issue URL for item N'); s.add_argument('n', type=int); s.add_argument('url')
    f.add_parser('sync', help='tick items whose issue is closed')
    s = sub.add_parser('update', help='check for or install a new kit release'); s.add_argument('--check', action='store_true')
    sub.add_parser('version')
    sub.add_parser('notices', help='updates, fixed issues and unshared feedback worth mentioning')
    s = sub.add_parser('digest', help='summarise a big log/JSON file deterministically'); s.add_argument('file')
    r = sub.add_parser('run', help='orchestration step tracking').add_subparsers(dest='action', required=True)
    s = r.add_parser('log'); s.add_argument('task'); s.add_argument('step'); s.add_argument('--provider', required=True)
    s.add_argument('--model', default=''); s.add_argument('--tokens-in', type=int, default=0); s.add_argument('--tokens-out', type=int, default=0)
    s.add_argument('--seconds', type=float, default=0); s.add_argument('--result', default='ok'); s.add_argument('--note', default='')
    s = r.add_parser('report'); s.add_argument('task', nargs='?')

    a = p.parse_args(argv)
    try:
        if a.cmd == 'init':
            cfg = core.init(a.dir, a.name, a.pack, a.repo)
            out(f"Workspace '{cfg['name']}' created in {Path(a.dir).resolve()} (packs: {', '.join(cfg['packs']) or 'none'}).\n"
                f"Next: cd {a.dir} && ws status   — then see docs/SETUP.md for Claude, Codex and MCP.")
            return 0
        if a.cmd == 'packs':
            out({n: core.pack_manifest(n)['description'] for n in core.available_packs()}); return 0
        if a.cmd == 'version':
            out(core.kit_meta()['version']); return 0
        if a.cmd == 'update':
            res = core.check_update(force=True)
            if a.check or not res.get('update_available'):
                out(res); return 0
            out(core.update_kit()); return 0
        if a.cmd == 'doctor':
            try:
                root = core.find_root()
            except core.WsError:
                root = None
            out(core.doctor(root)); return 0
        root = core.find_root()
        if a.cmd == 'status': out(core.status(root))
        elif a.cmd == 'map': out(core.codebase_map(root, a.repo))
        elif a.cmd == 'pack': out(core.pack_add(root, a.name))
        elif a.cmd == 'notices':
            out('\n'.join(f"- {n['message']} → {n['suggest']}" for n in core.notices(root)) or 'Nothing to report.')
        elif a.cmd == 'validate':
            res = core.validate(root); out(res); return 0 if res['valid'] else 1
        elif a.cmd == 'task':
            if a.action == 'new': out(core.task_new(root, a.id, a.title, a.objective, a.branch, a.repo))
            elif a.action == 'list': out(core.task_list(root))
            elif a.action == 'find': out(core.task_find(root, a.ref))
            else:
                res = core.task_read(root, a.id, a.section)
                out(res['text'] if 'text' in res else res)
        elif a.cmd == 'claim': out(core.claim(root, a.id, a.worker))
        elif a.cmd == 'release': out(core.release(root, a.id, a.worker, a.token))
        elif a.cmd == 'checkpoint':
            notes = dict(n.split('=', 1) for n in a.note)
            out(core.checkpoint(root, a.id, a.status, a.next, a.expected_sha, a.worker, a.token, notes))
        elif a.cmd == 'search': out(core.search(root, a.query))
        elif a.cmd == 'lesson':
            out(core.lesson_add(root, a.text, a.tag) if a.action == 'add' else '\n'.join(core.lesson_search(root, a.query)) or 'No lessons match.')
        elif a.cmd == 'feedback':
            if a.action == 'add': out(core.feedback_add(root, a.text, a.kind, a.source))
            elif a.action == 'submit': out(core.feedback_submit(root, a.n, a.yes))
            elif a.action == 'link': out(core.feedback_link(root, a.n, a.url))
            elif a.action == 'sync': out(core.feedback_sync(root))
            else: out([f"{i['n']}. {'[x]' if i['done'] else '[ ]'} {i['kind']}: {i['text']}" + (f" ({i['issue']})" if i['issue'] else '')
                       for i in core.feedback_items(root) if a.all or not i['done']] or 'No open feedback.')
        elif a.cmd == 'digest': out(core.digest_file(a.file))
        elif a.cmd == 'run':
            if a.action == 'log':
                out(core.run_log(root, a.task, a.step, a.provider, a.model, a.tokens_in, a.tokens_out, a.seconds, a.result, a.note))
            else: out(core.run_report(root, a.task))
        return 0
    except (core.WsError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f'ws: {exc}', file=sys.stderr)
        if not isinstance(exc, core.WsError):
            print('If this looks like a bug in ws, record it: ws feedback add "<what you ran and saw>" --kind bug', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
