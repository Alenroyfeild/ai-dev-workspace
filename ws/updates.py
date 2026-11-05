"""Read-only installation preflight; update application remains in core."""
import subprocess

from . import core


def kit_preflight():
    report = {'installation': 'package' if core.PACKAGED else 'source',
              'branch': None, 'upstream': None, 'ahead': None, 'behind': None,
              'dirty_files': [], 'local_commits': [], 'choices': [],
              'notes': ['Local refs only; no fetch performed. Ahead/behind may be stale.']}
    if core.PACKAGED:
        report.update(state='package', choices=[
            'For pipx, run pipx upgrade ai-dev-workspace outside ws.',
            'For a pip-managed environment, reinstall from the original install source.'])
        return report
    if not (core.KIT / '.git').exists():
        report.update(state='not-a-clone', choices=['Download a new release or update using the original install method.'])
        return report

    def git(*args, optional=False):
        # status must not refresh the index or launch a configured fsmonitor hook.
        run = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                              '-C', str(core.KIT), *args], capture_output=True,
                             encoding='utf-8', errors='replace', timeout=5)
        if run.returncode:
            if optional: return ''
            raise core.WsError(run.stderr.strip() or 'Git could not inspect this installation.')
        return run.stdout

    try:
        report['head'] = git('rev-parse', '--verify', 'HEAD').strip()
        report['branch'] = git('symbolic-ref', '--quiet', '--short', 'HEAD', optional=True).strip() or None
        report['upstream'] = git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}', optional=True).strip() or None
        entries = iter(git('status', '--porcelain=v1', '-z').split('\0'))
        for entry in entries:
            if not entry: continue
            report['dirty_files'].append(entry[3:])
            if 'R' in entry[:2] or 'C' in entry[:2]:
                report['dirty_files'].append(next(entries))
        if git('rev-parse', '--is-shallow-repository').strip() == 'true':
            report['notes'].append('Shallow history: counts and commit lists cover available history only.')
        upstream = report['upstream']
        if upstream:
            report['ahead'], report['behind'] = map(int, git('rev-list', '--left-right', '--count', 'HEAD...@{upstream}').split())
        else:
            report['notes'].append('No upstream: local history is listed; uniqueness against a remote is unknown.')
        ahead, behind = report['ahead'], report['behind']
        state = ('detached' if not report['branch'] else 'no-upstream' if not upstream else
                 'diverged' if ahead and behind else 'ahead' if ahead else 'behind' if behind else 'clean')
        report['state'] = state
        if ahead or not upstream:
            commits = git('log', '--format=%h %s', '-n', '21', '@{upstream}..HEAD' if upstream else 'HEAD').splitlines()
            report['local_commits'] = commits[:20]
            if len(commits) > 20:
                report['notes'].append('Showing the newest 20 commits; review the full Git log before choosing.')
            report['choices'] = ['Keep local work and skip the update.',
                                 'Review local commits, then merge the intended upstream manually.',
                                 'Review local commits, then rebase onto the intended upstream manually.']
        elif behind:
            report['choices'] = ['A fast-forward is possible against local refs; review, then run ws update.']
        else:
            report['choices'] = ['HEAD matches its local upstream ref; nothing was changed.']
        if state == 'detached':
            report['choices'].insert(0, 'Detached HEAD: choose a branch manually before updating.')
        if report['dirty_files']:
            if state == 'clean': report['state'] = 'dirty'
            report['choices'].insert(0, 'Commit or stash dirty files before attempting any update.')
    except (OSError, subprocess.TimeoutExpired, core.WsError, ValueError) as exc:
        report.update(state='unavailable', error=str(exc), choices=['Inspect the installation with Git; nothing was changed.'])
    return report
