"""Deterministic synthetic long-lived workspace based on checked-in beta.6 templates."""
import base64
import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / 'beta6'
TOKEN = 'a' * 32  # Synthetic local claim, not a credential.
LATEST_DECISION = 'Decision: latest synthetic decision uses violet markers.'
NEXT_ACTION = 'Review the synthetic handoff before continuing.'
EARLY_SEARCH = 'orchardanchor'


def _copy_templates(source, target, replacements):
    for item in sorted(source.rglob('*')):
        if not item.is_file():
            continue
        text = item.read_text(encoding='utf-8')
        for marker, value in replacements.items():
            text = text.replace(marker, value)
        relative = item.relative_to(source)
        if relative.name.endswith('.template'):
            relative = relative.with_name(relative.name[:-len('.template')])
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')


def _handoff():
    lines = []
    for number in range(1, 131):
        day = datetime.date(2026, 10, 1) + datetime.timedelta(days=(number - 1) * 24 // 129)
        lines.append('Checkpoint %03d (%s): Synthetic progress describes a stable sample record, the current observation, '
                     'the reason for review and the expected outcome. Synthetic fixture data only.' % (number, day.isoformat()))
        if number <= 49:
            anchor = EARLY_SEARCH if number == 3 else 'fixturetopic%03d' % number
            lines.append('Decision: Synthetic decision %03d on %s keeps %s for later review.' % (number, day.isoformat(), anchor))
        if number <= 14:
            marker = hashlib.sha256(('capture-%02d' % number).encode()).hexdigest()[:16]
            constraint = ('Only retain synthetic observation ' + 'context ' * (90 if number == 14 else 5) + 'until reviewed.')
            lines.extend(['<!-- ws:captured:' + marker + ' -->',
                          '### Captured 2026-10-%02d (unverified transcript)' % number,
                          'User constraints:', '- ' + constraint,
                          'Last assistant summary / next step: Next step: review the synthetic observation.',
                          '<!-- /ws:captured -->'])
    lines.append('Syntheticparagraphwithmissingspaces' * 12 + '.')
    lines.append(LATEST_DECISION)
    return '\n'.join(lines)


def create(home):
    """Create only synthetic files inside the caller's disposable HOME; return (workspace, repo)."""
    home = Path(home).resolve()
    home.mkdir(parents=True, exist_ok=True)
    repo = home / 'non-code-repo'; repo.mkdir()
    workspace = home / '.ai-dev-workspace' / 'non-code-repo'
    old_kit = home / 'legacy-beta6-kit'; old_kit.mkdir()
    env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TMPDIR') if key in os.environ}
    env.update(HOME=str(home), USERPROFILE=str(home), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_DATE='2026-10-01T00:00:00Z', GIT_COMMITTER_DATE='2026-10-01T00:00:00Z')
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], env=env, check=True, capture_output=True)
    (repo / 'notes.md').write_text('Synthetic non-code notes.\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(repo), 'add', 'notes.md'], env=env, check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-qm', 'Synthetic non-code fixture'], env=env, check=True, capture_output=True)
    replacements = {'{{WORKSPACE}}': workspace.as_posix(), '{{REPO}}': repo.as_posix(),
                    '{{OLD_KIT}}': old_kit.as_posix(), '{{HOME}}': home.as_posix()}
    _copy_templates(TEMPLATES / 'workspace', workspace, replacements)
    _copy_templates(TEMPLATES / 'repo', repo, replacements)
    state_text = (TEMPLATES / 'repo-start.json.template').read_text(encoding='utf-8')
    for marker, value in replacements.items(): state_text = state_text.replace(marker, value)
    state = json.loads(state_text)
    state['exclude'] = (repo / '.git/info/exclude').as_posix()
    for name, record in state['files'].items():
        record['sha'] = hashlib.sha256((repo / name).read_bytes()).hexdigest()
    (repo / '.ws-start.json').write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    exclude = (TEMPLATES / 'git-exclude.template').read_bytes()
    if base64.b64decode(state['exclude_block']) not in exclude:
        raise ValueError('beta.6 exclude template does not match its ownership record')
    (repo / '.git/info/exclude').write_bytes(exclude)
    codex = repo / '.codex/config.toml'
    original = codex.read_text(encoding='utf-8')
    if 'enabled = true' not in original:
        raise ValueError('beta.6 Codex template changed unexpectedly')
    codex.write_text(original.replace('enabled = true', 'enabled = false', 1) + '\n# Synthetic user edit.\n', encoding='utf-8')
    task = (TEMPLATES / 'task.md.template').read_text(encoding='utf-8')
    for old, new in (('{{id}}', 'main'), ('{{title}}', 'Synthetic main task'), ('{{date}}', '2026-10-01'),
                     ('status: ready', 'status: in_progress'), ('branch:\n', 'branch: main\n'),
                     ('repo:\n', 'repo: ' + repo.as_posix() + '\n'), ('claimed_by:\n', 'claimed_by: fixture-worker\n'),
                     ('claim_token:\n', 'claim_token: ' + TOKEN + '\n'),
                     ('claimed_at:\n', 'claimed_at: 2026-10-01T00:00:00+00:00\ncheckpoint_count: 130\n')):
        task = task.replace(old, new)
    task = task.replace('## Next action\nRead the code involved and fill Evidence.', '## Next action\n' + NEXT_ACTION)
    task = task.replace('## Handoff\n\n## Do not redo', '## Handoff\n\n' + _handoff() + '\n\n## Do not redo\n- Do not repeat the synthetic rejected step.')
    task_path = workspace / 'vault/Tasks/main.md'; task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(task, encoding='utf-8')
    claims = workspace / '.ws/claims'; claims.mkdir(parents=True, exist_ok=True)
    (claims / 'main.json').write_text(json.dumps({'worker': 'fixture-worker', 'token': TOKEN}) + '\n', encoding='utf-8')
    (workspace / '.ws/lock').touch()
    return workspace, repo
