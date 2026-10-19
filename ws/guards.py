"""Opt-in PreToolUse guards (guards pack): deny destructive shell/git commands, secrets and newly muted tests.

Claude Code and Codex read the same deny JSON. Any error lets the tool run (both clients fail open), so a guard
bug never blocks work; WS_GUARDS=off in the shell that starts the assistant turns every rule off.
"""
import base64
import os
import posixpath
import re
import shlex
from pathlib import Path

from . import core

HOME_OR_ROOT = {'/', '/*', '~', '~/', '~/*', '$HOME', '$HOME/', '$HOME/*', '${HOME}', '${HOME}/'}
TOKENS = re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{40,}|sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b')


def secret_values(text):
    """Real-looking secrets in text. Stricter than redact (which may over-redact): $VAR and placeholders do not count."""
    found = set(TOKENS.findall(text)) | set(re.findall(r'-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)', text, re.S))
    for match in list(core.SECRET_RE.finditer(text)) + list(core.URL_CREDENTIALS_RE.finditer(text)):
        hit = match[0].rsplit(':', 1)[-1].rstrip('@') if match.re is core.URL_CREDENTIALS_RE else match[0]
        hit = hit.strip()
        if not re.match(r'(?i)bearer\b', hit): hit = re.split(r'\s*[:=]\s*', hit, maxsplit=1)[-1]  # the first : or = only; base64 padding keeps its =
        value = (hit.split() or [''])[-1].strip('"\'')
        if value[:1] in '$<{' or re.search(r'(?i)^(your|change|replace|insert|todo)|example|placeholder|dummy|xxx', value): continue
        if len(value) >= 12 and re.search(r'\d', value) and re.search(r'[A-Za-z]', value): found.add(value)
    return found


def looks_secret(text):
    return bool(secret_values(text))


SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish'}
MUTED = re.compile(r'@(?:pytest\.mark\.skip|unittest\.skip)\b|@(?:pytest\.mark\.skipif|unittest\.skipIf)\(\s*(?:True|1)\b|\b(?:it|test|describe)\.(?:only|skip)\(|\bx(?:it|test|describe)\(|\bt\.Skip(?:Now)?\(')


def _words(command):
    try: return shlex.split(command, comments=True)
    except ValueError: return command.split()


def _segments(command):
    """Each simple command in a pipeline or && / ; chain, as words; `sudo`/`command` prefixes dropped."""
    for part in re.split(r'&&|\|\||[;|\n]', command):
        words = _words(part)
        while words and words[0] in ('sudo', 'command', 'exec', 'env', 'nohup', 'time'): words = words[1:]
        if words: yield words


def _canon(path):
    """Path with ~, $HOME, ${HOME}, $env:USERPROFILE swapped for the real home, then slashes, `/.`, `//` and a trailing `/*` folded."""
    home = os.path.expanduser('~')
    path = re.sub(r'(?i)^(?:~|\$home|\$\{home\}|\$env:userprofile|\$env:home|\$userprofile|\$\{userprofile\}|%userprofile%|%homedrive%%homepath%)(?=$|[\\/])', lambda _: home, path)
    path = re.sub(r'/\.?\*$', '/', re.sub(r'[\\/]+', '/', path))
    path = re.sub(r'(?i)^/([a-z])(?=/|$)', r'\1:', path)  # Git Bash /c/Users -> c:/Users
    return posixpath.normpath(path).lower()  # case-insensitive on every OS so a Windows home matches however it is typed


def _is_home(path):
    """The user's home folder, however spelled."""
    return _canon(path) == _canon('~')


def _is_root(path):
    """The filesystem root or a drive root: /, C:/, C:/*, /c/*."""
    return _canon(path) == '/' or bool(re.fullmatch(r'[a-z]:', _canon(path)))


_PS_WRAP = re.compile(r'(?is)(?<![\w.-])(?:[^\s;&|"\']*[\\/])?(?:powershell|pwsh)(?:\.exe)?\s(?:.*?\s)?-(c|command|commandwithargs|ec|encodedcommand)\b\s*(.*)')
_CMD_WRAP = re.compile(r'(?is)(?<![\w.-])(?:[^\s;&|"\']*[\\/])?cmd(?:\.exe)?\s+(?:.*?\s)?/[ck]\s+(.*)')


def _unquote(text):
    text = text.strip().replace('\\"', '"')
    return text[1:].rstrip('"\'') if text[:1] in '"\'' else text


def _wrapped(command):
    """Inner command strings of powershell/pwsh -Command and cmd /c invocations, so the same rules see them under the Bash tool."""
    for match in _PS_WRAP.finditer(command):
        inner = _unquote(match[2])
        if match[1].lower() in ('ec', 'encodedcommand'):
            try: inner = base64.b64decode(inner.strip('"\' '), validate=True).decode('utf-16-le')
            except ValueError: continue  # includes UnicodeDecodeError and binascii.Error
        yield inner
    for match in _CMD_WRAP.finditer(command):
        yield _unquote(match[1])


def command_reason(command):
    for inner in _wrapped(command):
        why = command_reason(inner) or powershell_reason(inner) or cmd_reason(inner)
        if why: return why
    for words in _segments(command):
        name, args = os.path.basename(words[0]), words[1:]
        if name in SHELLS and len(args) >= 2 and re.fullmatch(r'-\w*c', args[0]):  # bash -lc "<command>"
            inner = command_reason(args[1])
            if inner: return inner
            continue
        flags = ''.join(a[1:] for a in args if a.startswith('-') and not a.startswith('--'))
        if name == 'rm' and ('r' in flags.lower() or '--recursive' in args) and ('f' in flags or '--force' in args):
            hit = [a for a in args if a in HOME_OR_ROOT or _is_home(a) or _is_root(a)]
            if hit: return f'rm -rf on {hit[0]} would delete your home folder or the filesystem root.'
        while name == 'git' and args and args[0].startswith('-'):  # global options: git -C dir, -c k=v, --no-pager ...
            args = args[2:] if args[0] in ('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path') else args[1:]
        if name == 'git' and args:
            sub, rest = args[0], args[1:]
            if sub == 'reset' and '--hard' in rest: return 'git reset --hard throws away uncommitted work.'
            if sub == 'push' and any(a in ('-f', '--force') or a.startswith('+') or (a.startswith('-') and not a.startswith('--') and 'f' in a) for a in rest):
                return 'Force push rewrites shared history; use --force-with-lease if you must.'
            if sub == 'clean' and any(a == '--force' or (a.startswith('-') and not a.startswith('--') and 'f' in a) for a in rest):
                return 'git clean -f deletes untracked files for good.'
    if looks_secret(command): return 'The command contains what looks like a secret (token, key or password).'
    return ''


PS_REMOVE = {'remove-item', 'rm', 'ri', 'del', 'erase', 'rd', 'rmdir'}


def _ps_flag(arg, full):
    """True when arg is -Name or an abbreviation of it (PowerShell accepts unambiguous prefixes), e.g. -r, -fo, -Recurse:$true; -Force:$false is off."""
    name, _, value = arg[1:].partition(':')
    return arg[:1] == '-' and bool(name) and full.startswith(name.lower()) and value.lower() not in ('$false', 'false', '0')


def _ps_home_or_root(a):
    return not a.startswith('-') and (not a.strip('\\/') or _is_home(a) or _is_root(a))


def powershell_reason(command):
    """Remove-Item (and aliases) -Recurse -Force on home or a drive root, also when piped in; git and secrets go through command_reason."""
    previous = []  # words of the pipeline stage before this one, whose output may be Remove-Item's target
    for part in re.split(r'&&|\|\||[;|\n]', command):
        words = [w.strip('"\'') for w in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', part)]
        while words and words[0] == '&': words = words[1:]
        before, previous = previous, words
        if not words or words[0].lower() not in PS_REMOVE: continue
        args = words[1:]
        if not (any(_ps_flag(a, 'recurse') for a in args) and any(_ps_flag(a, 'force') for a in args)): continue
        piped = [] if any(not a.startswith('-') for a in args) else before[1:] if len(before) > 1 else before
        for a in args + piped:
            if _ps_home_or_root(a):
                return f'Remove-Item -Recurse -Force on {a} would delete your home folder or a drive root.'
    return ''


CMD_REMOVE = {'rd', 'rmdir', 'del', 'erase'}


def cmd_reason(command):
    """cmd.exe rd/rmdir/del /s on home or a drive root (%USERPROFILE%, C:\\, %SystemDrive%\\)."""
    for part in re.split(r'&&|\|\||[&;|\n]', command):
        words = [w.strip('"\'') for w in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', part)]
        while words and words[0].lower() in ('call', '@'): words = words[1:]
        if not words or words[0].lower().lstrip('@') not in CMD_REMOVE: continue
        args = words[1:]
        if not any(a.lower() == '/s' for a in args): continue
        for a in args:
            if not re.fullmatch(r'/[a-z?]', a, re.I) and (_ps_home_or_root(a) or a.lower().rstrip('\\/') == '%systemdrive%'):
                return f'{words[0]} /s on {a} would delete your home folder or a drive root.'
    return ''


def _added(tool_input, cwd):
    """(new text, removed text) a file edit would introduce, for Claude Write/Edit/MultiEdit and Codex apply_patch."""
    if 'edits' in tool_input and isinstance(tool_input['edits'], list):
        pairs = [(e.get('new_string', ''), e.get('old_string', '')) for e in tool_input['edits'] if isinstance(e, dict)]
        return ''.join(p[0] for p in pairs), ''.join(p[1] for p in pairs)
    if 'new_string' in tool_input: return str(tool_input['new_string']), str(tool_input.get('old_string', ''))
    if 'content' in tool_input:
        old = ''
        try: old = (Path(cwd or '.') / str(tool_input.get('file_path', ''))).read_text(encoding='utf-8', errors='replace')
        except OSError: pass
        return str(tool_input['content']), old
    return '', ''


def reason(tool_name, tool_input, cwd=None):
    if os.environ.get('WS_GUARDS', '').lower() in ('off', '0', 'false'): return ''
    if not isinstance(tool_input, dict): return ''
    command = tool_input.get('command', '')
    if isinstance(command, list): command = shlex.join(map(str, command))  # Codex sends argv, e.g. ["bash", "-lc", "..."]
    if not isinstance(command, str): command = ''
    if tool_name == 'apply_patch' or command.lstrip().startswith('*** Begin Patch'):
        lines = command.splitlines()
        new = '\n'.join(l[1:] for l in lines if l.startswith('+')); old = '\n'.join(l[1:] for l in lines if l.startswith('-'))
    elif command:
        return command_reason(command) or (powershell_reason(command) if tool_name == 'PowerShell' else '')
    else:
        new, old = _added(tool_input, cwd)
    if len(MUTED.findall(new)) > len(MUTED.findall(old)): return 'This edit skips or narrows tests (skip/only); fix the test or ask the user first.'
    if secret_values(new) - secret_values(old): return 'This edit writes what looks like a secret (token, key or password) into a file.'
    return ''


def hook(payload):
    """PreToolUse hook output: deny with a reason, or {} to allow."""
    why = reason(payload.get('tool_name', ''), payload.get('tool_input'), payload.get('cwd'))
    if not why: return {}
    why = f'ws guards: {why} If the user really wants this, they can run it themselves or start the assistant with WS_GUARDS=off.'
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': why}}
