"""Opt-in PreToolUse guards (guards pack): deny destructive shell/git commands, secrets and newly muted tests.

Claude Code and Codex read the same deny JSON. Any error lets the tool run (both clients fail open), so a guard
bug never blocks work; WS_GUARDS=off in the shell that starts the assistant turns every rule off.
A best-effort safety net, not a sandbox: it reads command text, it never runs it, and a determined bypass exists.
"""
import base64
import collections
import itertools
import json
import os
import posixpath
import re
import shlex
from pathlib import Path

from . import core

HOME_OR_ROOT = {'/', '/*', '~', '~/', '~/*', '$HOME', '$HOME/', '$HOME/*', '${HOME}', '${HOME}/'}
TOKENS = re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{40,}|(?<![\w-])sk-(?=[A-Za-z_-]{0,60}\d)[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b')
# password=..., token: "...": explicit secret names, so a shorter value (8+) with no digit still counts; identifiers and calls do not.
_LOOSE = re.compile(r'(?i)(?<![A-Za-z0-9])(password|passwd|pwd|secret|token)["\']?\s*([:=])\s*(?:"([^"\n]*)"|\'([^\'\n]*)\'|([^\s"\'`;&|<>,()\[\]{}]+))')
_PLACEHOLDER = re.compile(r'(?i)^(your|change|replace|insert|todo)|example|placeholder|dummy|xxx|^(password|passwd|secret|token|redacted|hidden|string|required|none|null|true|false|undefined)$')
_CODEISH = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|[a-z]+(?:_[a-z0-9]+)+|[A-Z]+(?:_[A-Z0-9]+)+|[a-z]{2,}(?:[A-Z][a-z]{2,}[0-9]*)+|[A-Z][A-Za-z]*(?:-[A-Z][A-Za-z0-9]*)+')  # last: PowerShell Verb-Noun


def _placeholder(value, following=''):
    """$VAR, <tag>, {template}, placeholder words, repeated characters and code (calls, a.b.c, snake_case, camelCase) are not secrets."""
    return (value[:1] in '$<{%' or bool(_PLACEHOLDER.search(value)) or bool(re.fullmatch(r'(.)\1*', value)) or following == '('
            or bool(_CODEISH.fullmatch(value)) or bool(re.search(r'\w\(', value)))


def secret_values(text):
    """Real-looking secrets in text. Stricter than redact (which may over-redact): $VAR and placeholders do not count."""
    found = set(TOKENS.findall(text)) | set(re.findall(r'-----BEGIN [^-]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [^-]*PRIVATE KEY(?: BLOCK)?-----|\Z)', text, re.S))
    for match in list(core.SECRET_RE.finditer(text)) + list(core.URL_CREDENTIALS_RE.finditer(text)):
        hit = match[0].rsplit(':', 1)[-1].rstrip('@') if match.re is core.URL_CREDENTIALS_RE else match[0]
        hit = hit.strip()
        if not re.match(r'(?i)bearer\b', hit): hit = re.split(r'\s*[:=]\s*', hit, maxsplit=1)[-1]  # the first : or = only; base64 padding keeps its =
        value = (hit.split() or [''])[-1].strip('"\'')
        if _placeholder(value, text[match.end():match.end() + 1]) or value[:3] == 'sk-' and re.match(r'[\w-]', text[max(match.start() - 1, 0):match.start()] or ' '): continue  # task-sk-... is an id
        if len(value) >= 12 and re.search(r'\d', value) and re.search(r'[A-Za-z]', value): found.add(value)
    for match in _LOOSE.finditer(text):
        quoted = match[3] is not None or match[4] is not None
        value = match[3] if match[3] is not None else match[4] if match[4] is not None else match[5]
        if len(value) < 8 or not re.search(r'[A-Za-z]', value) or (' ' in value and quoted) or _placeholder(value, text[match.end():match.end() + 1]): continue
        if match[1].lower() == 'pwd' and re.search(r'[\\/]', value): continue  # $PWD is a path
        if not quoted and match[2] == ':' and value.isalpha(): continue  # `password: Optional[str]`, YAML words
        found.add(value)
    return found


def looks_secret(text):
    return bool(secret_values(text))


SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish', 'su'}
MUTED = re.compile(
    r'@(?:pytest\.mark\.skip|unittest\.skip|skip|unittest\.expectedFailure|expectedFailure|pytest\.mark\.xfail|Disabled|Ignore)\b'
    r'|@(?:pytest\.mark\.skipif|unittest\.skipIf|skipIf)\(\s*(?:True|1|not\s+(?:False|0))\b|@(?:unittest\.)?skipUnless\(\s*(?:False|0)\b'
    r'|\bpytest\.skip\(|\.skipTest\(|\bthis\.skip\(|(?<![\w.])(?:fit|fdescribe)\(\s*[\'"`]|(?<![\w.])x(?:it|test|describe|context)(?:\(|[ \t]+["\'])|\b(?:it|test|describe|context|suite|specify)(?:\.concurrent)?\.(?:only|skip|todo|failing)\b'
    r'|\b[tb]\.Skip\w*\(|#\[ignore\b|(?m:^[ \t]*skip[ \t]+["\'])')


def _exe(word):
    """Lower-case command name of a word: path and .exe dropped, so `/bin/rm`, `Rm.EXE` and an unquoted `C:\\...\\cmd.exe` (backslashes eaten) all resolve."""
    base = re.split(r'[\\/]', word)[-1].lower()
    for tool in ('powershell', 'pwsh', 'cmd'):
        if word.lower().endswith(tool + '.exe'): return tool
    return base[:-4] if base.endswith('.exe') else base


Cmd = collections.namedtuple('Cmd', 'words bodies pipe_in src start')  # one simple command; start is where its first word begins in src


class _Frame:
    __slots__ = ('mode', 'words', 'cur', 'started', 'bodies', 'start', 'pipe')

    def __init__(self, mode):
        self.mode, self.words, self.cur, self.started, self.bodies, self.start, self.pipe = mode, [], [], False, [], 0, None


_PLAIN = re.compile(r'[^\s\'"\\$`;&|()<>#]+')
_PLAIN_PS = re.compile(r'[^\s\'"$`;&|(){}<>#]+')
_REDIRECT_OP = re.compile(r'>{1,2}[|&]?')
_DQ = re.compile(r'[^"\\$`]+')
_HEREDOC = re.compile(r'<<(-?)[ \t]*(?:"([^"\n]*)"|\'([^\'\n]*)\'|\\?([A-Za-z_][\w.-]*))')
_KEYWORDS = frozenset(('if', 'then', 'do', 'else', 'elif', 'while', 'until', '!', '{', '}', 'fi', 'done', 'esac'))


def _scan(text, ps=False):
    """Simple commands of a command line, in one linear pass: split on ; & && | || |& newline ( ) $( ) ` and { } (PowerShell);
    quotes, comments and heredoc bodies stay data (a quoted `git push -f` is text); `$( )` inside double quotes and unquoted heredocs still run.
    ps=True reads PowerShell/cmd: backslash is a path character, backtick the escape."""
    out, n, i = [], len(text), 0
    root = _Frame('cmd'); stack = [root]; top = o = root; pending = []  # o: frame owning the word being built (not a quote frame)
    plain = _PLAIN_PS if ps else _PLAIN

    def push(mode):
        nonlocal top, o
        top = _Frame(mode); stack.append(top)
        if mode != 'dq': o = top

    def pop():
        nonlocal top, o
        stack.pop(); top = stack[-1]
        o = next(f for f in reversed(stack) if f.mode != 'dq')

    def add(piece):
        if not o.started:
            o.started = True
            if not o.words: o.start = i
        o.cur.append(piece)

    def endword():
        if o.started: o.words.append(''.join(o.cur)); o.cur = []; o.started = False

    def emit(piped):
        endword()
        words, k = o.words, 0
        while k < len(words) and words[k] in _KEYWORDS: k += 1
        words = words[k:]
        if words: out.append(Cmd(words, o.bodies, o.pipe, text, o.start))
        o.pipe = words if piped and words else None
        o.words, o.bodies = [], []

    while i < n:
        c = text[i]
        if top.mode == 'dq':
            if c == '"': pop(); i += 1
            elif c == '`' and ps: add(text[i + 1:i + 2]); i += 2
            elif c == '`': push('bt'); i += 1
            elif c == '\\':
                nx = text[i + 1:i + 2]
                if ps or nx not in ('$', '"', '\\', '`', '\n'): add('\\'); i += 1
                else:
                    if nx != '\n': add(nx)
                    i += 2
            elif c == '$':
                nx = text[i + 1:i + 2]
                if nx == '(': push('sub'); i += 2
                elif nx == '{': j = text.find('}', i); j = n - 1 if j < 0 else j; add(text[i:j + 1]); i = j + 1
                else: add('$'); i += 1
            else: m = _DQ.match(text, i); add(m[0]); i = m.end()
            continue
        if c == '\n':
            emit(False); i += 1
            for tag, tabs, quoted, sink in pending:
                lines = []
                while i < n:
                    j = text.find('\n', i); j = n if j < 0 else j
                    line = text[i:j].rstrip('\r'); i = min(j + 1, n)
                    if (line.lstrip('\t') if tabs else line) == tag: break
                    lines.append(line)
                sink.append('\n'.join(lines))
                if not quoted:  # an unquoted heredoc still runs $( ) and backticks in its body
                    for m in re.finditer(r'\$\(([^()]*)\)|`([^`]*)`', sink[-1]): out.extend(_scan(m[1] if m[1] is not None else m[2], ps))
            pending.clear()
        elif c.isspace(): endword(); i += 1
        elif c == '\\' and not ps:
            nx = text[i + 1:i + 2]
            if nx == '\n': i += 2
            elif nx == '\r' and text[i + 2:i + 3] == '\n': i += 3
            elif nx: add(nx); i += 2
            else: i += 1  # a trailing backslash continues nothing
        elif c == '`' and ps:
            nx = text[i + 1:i + 3]
            if nx[:1] == '\n': i += 2
            elif nx == '\r\n': i += 3
            else: add(nx[:1]); i += 2
        elif c == '`':
            if top.mode == 'bt': emit(False); pop()
            else: push('bt')
            i += 1
        elif c == "'":
            j = text.find("'", i + 1)
            add(text[i + 1:] if j < 0 else text[i + 1:j]); i = n if j < 0 else j + 1
        elif c == '"': add(''); push('dq'); i += 1
        elif c == '$':
            nx = text[i + 1:i + 2]
            if nx == '(': push('sub'); i += 2
            elif nx == "'" and not ps:  # $'...' with backslash escapes
                j = i + 2
                while j < n and text[j] != "'": j += 2 if text[j] == '\\' else 1
                add(text[i + 2:j]); i = j + 1
            elif nx == '{': j = text.find('}', i); j = n - 1 if j < 0 else j; add(text[i:j + 1]); i = j + 1
            else: add('$'); i += 1
        elif c == '(': emit(False); push('sub'); i += 1
        elif c == ')':
            emit(False)
            if top.mode == 'sub': pop()
            i += 1
        elif c == ';': emit(False); i += 1
        elif c == '&':
            nx = text[i + 1:i + 2]
            if nx == '&': emit(False); i += 2
            elif nx == '>' or (o.cur and o.cur[-1][-1:] in ('<', '>')): add('&'); i += 1  # 2>&1, &>file
            else: emit(False); i += 1
        elif c == '|':
            nx = text[i + 1:i + 2]
            emit(nx != '|'); i += 2 if nx in ('|', '&') else 1
        elif c in '{}' and ps: emit(False); i += 1
        elif c == '#':
            if o.started: add('#'); i += 1
            else: j = text.find('\n', i); i = n if j < 0 else j
        elif c == '>':  # `a>f` is the word a, then >f; an fd (2>f) or & (&>f) stays attached to it
            if o.started and not (len(o.cur) == 1 and re.fullmatch(r'\d*|&', o.cur[0])): endword()
            m = _REDIRECT_OP.match(text, i); add(m[0]); i = m.end()
        elif c == '<':
            m = _HEREDOC.match(text, i) if text.startswith('<<', i) and not text.startswith('<<<', i) else None
            if m: pending.append((m[2] or m[3] or m[4], bool(m[1]), m[2] is not None or m[3] is not None or '\\' in m[0], o.bodies)); i = m.end()
            else: k = 3 if text.startswith('<<<', i) else 1; add('<' * k); i += k
        else: m = plain.match(text, i); add(m[0]); i = m.end()
    for frame in stack:
        if frame.mode != 'dq': o = frame; emit(False)
    return out


# Wrapper commands, with the short options that take a value, so `sudo -u me git ...` or `timeout 5 git ...` still reach the real command.
_WRAP = {'sudo': 'ughpCTrtUDR', 'doas': 'uC', 'env': 'uCS', 'command': '', 'exec': 'a', 'nohup': '', 'time': 'fo', 'nice': 'n', 'ionice': 'cnp', 'timeout': 'sk',
         'setsid': '', 'stdbuf': 'ioe', 'watch': 'n', 'busybox': '', 'xargs': 'nILPsdEa', 'wsl': 'du'}

# Long options that take a separate value (`sudo --user root git ...`); `--user=root` is one word and needs nothing. GNU getopt accepts unambiguous abbreviations.
_WRAP_LONG = {'sudo': ('--user', '--group', '--host', '--prompt', '--chdir', '--close-from', '--role', '--type', '--other-user', '--command-timeout', '--login-class'),
              'env': ('--chdir', '--unset', '--split-string', '--argv0'), 'timeout': ('--signal', '--kill-after'), 'nice': ('--adjustment',),
              'ionice': ('--class', '--classdata', '--pid', '--pgid', '--uid'), 'stdbuf': ('--input', '--output', '--error'), 'time': ('--format', '--output'), 'watch': ('--interval',),
              'xargs': ('--max-args', '--max-lines', '--max-procs', '--max-chars', '--delimiter', '--arg-file', '--eof', '--process-slot-var')}


def _long_takes_value(name, option):
    return len(option) > 2 and any(long.startswith(option) for long in _WRAP_LONG.get(name, ()))


def _strip(words):
    """(words without NAME=value prefixes and wrapper commands + their options, whether xargs was one of them)."""
    xargs, k, n = False, 0, len(words)
    while k < n:
        if re.match(r'[A-Za-z_]\w*\+?=', words[k]): k += 1; continue
        name = _exe(words[k])
        if name not in _WRAP: break
        xargs = xargs or name == 'xargs'
        k += 1
        while k < n and words[k][:1] == '-' and words[k] != '-':
            option = words[k]; k += 1
            if option == '--': break
            if name == 'env':
                if option in ('-S', '--split-string'): return ['env', '-S', *words[k:]], xargs
                if option.startswith('--split-string=') or option.startswith('-S'):
                    payload = option.partition('=')[2] if option.startswith('--') else option[2:]
                    return ['env', '-S', payload, *words[k:]], xargs
            if option[:2] == '--': k += _long_takes_value(name, option) and k < n
            else:
                for j, char in enumerate(option[1:], 1):
                    if char in _WRAP[name]: k += j == len(option) - 1; break  # value is the next word unless attached (-n5)
        if name == 'timeout' and k < n and re.fullmatch(r'\d[\d.]*[smhd]?', words[k]): k += 1
    return words[k:], xargs


def _canon(path):
    """Path with ~, $HOME, ${HOME}, $env:USERPROFILE swapped for the real home, then slashes, `/.`, `//` and a trailing `/*` folded."""
    home = os.path.expanduser('~')
    path = re.sub(r'(?i)^(?:~|\$home|\$\{home\}|\$env:userprofile|\$\{env:userprofile\}|\$env:home|\$userprofile|\$\{userprofile\}|%userprofile%|%homedrive%%homepath%|\$env:homedrive\$env:homepath)(?=$|[\\/])', lambda _: home, path)
    path = re.sub(r'(?i)^(?:\$env:systemdrive|\$\{env:systemdrive\}|%systemdrive%|\$env:homedrive|%homedrive%)(?=$|[\\/])', 'c:', path)
    path = re.sub(r'/\.?\*(?:\.\*)?$', '/', re.sub(r'[\\/]+', '/', path))
    drive = r'(?:(?:mnt|cygdrive)/)?' if re.match(r'(?i)[a-z]:|/[a-z](?:/|$)', home) else r'(?:mnt|cygdrive)/'  # a bare /c is a drive only where home is on one
    path = re.sub(r'(?i)^/' + drive + r'([a-z])(?=/|$)', r'\1:', path)  # Git Bash /c/Users, WSL /mnt/c, Cygwin /cygdrive/c -> c:/Users
    return posixpath.normpath(path).lower()  # case-insensitive on every OS so a Windows home matches however it is typed


def _is_home(path):
    """The user's home folder or a folder that contains it (~/.., /Users, C:/Users), however spelled."""
    folded, home = _canon(path), _canon('~')
    return folded == home or home.startswith(folded.rstrip('/') + '/')


def _is_root(path):
    """The filesystem root or a drive root: /, C:/, C:/*, /c/*."""
    return _canon(path) == '/' or bool(re.fullmatch(r'[a-z]:', _canon(path)))


_WIPE_CWD = re.compile(r'(?:\./)*(?:\*|\.\*?|\.\./?)(?:/\*?)?')  # *, ., .*, .., ./* : everything in the current folder
_HOOK_FILE = re.compile(r'(?i)(?:^|[\\/])(?:\.claude[\\/]settings[\w.-]*\.json|\.codex[\\/]hooks\.json|\.agents[\\/]hooks\.json)$')
_NO_DISABLE = 'Ask the user to remove the guards pack themselves.'


_REDIR = re.compile(r'(?:\d+|&)?>{1,2}[|&]?(.*)', re.S)  # one word of a redirect: >f, >>f, 2>f, &>f, >|f, or a bare operator (the target is the next word)
_GUARD_TOOLS = ('Bash', 'PowerShell', 'Write', 'Edit', 'MultiEdit', 'Monitor', 'NotebookEdit')  # what the guards pack's matcher covers


def _guard_marks(text):
    return len(re.findall(r'\bguard\b|PreToolUse', text))


def _redirect_targets(words):
    targets = []
    for k, word in enumerate(words):
        m = _REDIR.fullmatch(word)
        if m: targets.append(m[1] or (words[k + 1] if k + 1 < len(words) else ''))  # appends too: they leave invalid JSON, which switches the hooks off
    return targets


def _operands(args):
    """Non-option words without redirects and their targets."""
    out, skip = [], False
    for a in args:
        if skip: skip = False; continue
        m = _REDIR.fullmatch(a)
        if m: skip = not m[1]
        elif a[:1] != '-': out.append(a)
    return out


def _hook_arg(word):
    """True when a word names a hook config file, also as -Path:file or of=file."""
    if word[:1] == '-' and ':' in word: word = word.partition(':')[2]
    elif word[:3] == 'of=': word = word[3:]
    return bool(_HOOK_FILE.search(word))


def _undoes_start(name, args):
    """`ws start --undo` (any spelling of the ws command and of the option): it removes the repo hooks the guards run from."""
    if re.fullmatch(r'python(?:w|[0-9.]*)|py', name):
        while args and args[0].startswith('-'):
            option, args = args[0], args[1:]
            if option == '-m': break
            if option.startswith('-c') or option in ('--help', '-V', '--version'): return False
            if option in ('-W', '-X'): args = args[1:]
        if not args: return False
        name, args = _exe(args[0]), args[1:]
    if name not in ('ws', 'ws-plugin'): return False
    while args and args[0].startswith('--workspace-root'):
        if args[0] == '--workspace-root': args = args[2:]
        elif args[0].startswith('--workspace-root='): args = args[1:]
        else: return False
    return bool(args and args[0] == 'start' and any(len(a) >= 3 and a[:2] == '--' and '--undo'.startswith(a) for a in args[1:]))


def _test_file(word):
    return bool(re.search(r'(?i)test|spec', word)) and not word.lower().endswith(('.md', '.txt', '.rst', '.json', '.yml', '.yaml'))


def _shell_command(args):
    """The -c string of `bash [-x] -lc '<command>'`, or None."""
    for k, arg in enumerate(args):
        if arg == '--': continue
        if arg[:1] != '-': return None
        if re.fullmatch(r'-\w*c', arg): return next((a for a in args[k + 1:] if a != '--'), None)
    return None


def _edits_hooks(name, args, words):
    """Shell commands that remove the guards pack or rewrite the assistant's hook config; the assistant must not switch its own guard off."""
    if any(args[k:k + 3] == ['pack', 'remove', 'guards'] for k in range(len(args))): return f'This would remove the guards pack. {_NO_DISABLE}'
    if _undoes_start(name, args): return f'This would remove the repo hooks (ws start --undo). {_NO_DISABLE}'
    inplace = name in ('sed', 'perl') and any(a[:1] == '-' and a[1:2] != '-' and 'i' in a for a in args)
    operands = _operands(args)
    if (any(_HOOK_FILE.search(t) for t in _redirect_targets(words))
            or (name in ('rm', 'mv', 'unlink', 'shred', 'truncate', 'tee') or inplace) and any(_hook_arg(a) for a in args)
            or name in ('cp', 'install', 'ln') and operands and _hook_arg(operands[-1])  # the destination; reading a hook file is fine
            or name == 'dd' and any(a[:3] == 'of=' and _hook_arg(a) for a in args)):
        return f'This would change the hook config that runs the guards. {_NO_DISABLE}'
    return ''


def _mutes(name, args, bodies):
    """True when a sed -i / perl -i script, echo/printf/cat/tee redirect or heredoc adds a skip/only marker to a test file."""
    if not any(_test_file(a) for a in args): return False
    redirect = any(a[:1] == '>' for a in args) or name == 'tee'
    inplace = name in ('sed', 'perl') and any(a[:1] == '-' and a[1:2] != '-' and 'i' in a for a in args)
    if not (redirect or inplace): return False
    texts = list(bodies) + ([a for a in args if a[:1] != '-'] if inplace or name in ('echo', 'printf') else [])
    for text in texts:
        sub = re.fullmatch(r's(.)(.*?)\1(.*?)\1[gI]*', text, re.S)
        if len(MUTED.findall(sub[3] if sub else text)) > len(MUTED.findall(sub[2] if sub else '')): return True
    return False


_GIT_VALUE = ('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env', '--super-prefix')  # global options that take the next word


def _simple(cmd, name, args, xargs, cwd_bad, budget, depth):
    """Reason for one simple command (wrappers and NAME=value already stripped), or ''."""
    if name in SHELLS:  # bash -lc "<command>", bash <<EOF ... EOF, bash <<< "<command>", echo "<command>" | bash
        inner = _shell_command(args)
        if inner is None and '<<<' in args[:-1]: inner = args[args.index('<<<') + 1]
        if inner is None and not cmd.bodies and cmd.pipe_in and _exe(cmd.pipe_in[0]) in ('echo', 'printf'): inner = ' '.join(cmd.pipe_in[1:])
        return next(filter(None, (command_reason(text, False, budget, depth + 1) for text in ([inner] if inner is not None else cmd.bodies))), '')
    if name == 'env' and args[:1] == ['-S'] and len(args) > 1:
        return command_reason(args[1] + ' ' + shlex.join(args[2:]), False, budget, depth + 1)
    if name == 'eval': return command_reason(' '.join(args), False, budget, depth + 1)
    if name in ('powershell', 'pwsh', 'cmd'):
        return next(filter(None, (_nested(inner, budget, depth) for inner in _wrapped(cmd, name, args, budget))), '')
    if name == 'apply_patch' and cmd.bodies: return next(filter(None, map(_patch_reason, cmd.bodies)), '')
    why = _edits_hooks(name, args, cmd.words)
    if why: return why
    if _mutes(name, args, cmd.bodies): return 'This command skips or narrows tests (skip/only); fix the test or ask the user first.'
    flags = ''.join(a[1:] for a in args if a.startswith('-') and not a.startswith('--'))
    if name == 'rm' and ('r' in flags.lower() or '--recursive' in args):
        targets = args if not xargs or any(a[:1] != '-' for a in args) else (cmd.pipe_in or [])[1:]
        hit = [a for a in targets if a in HOME_OR_ROOT or _is_home(a) or _is_root(a) or (cwd_bad and _WIPE_CWD.fullmatch(a))]
        if hit: return f'rm -r on {hit[0]} would delete your home folder or the filesystem root.'
    while name == 'git' and args and args[0].startswith('-'):  # global options: git -C dir, -c k=v, --no-pager ...
        args = args[2:] if args[0] in _GIT_VALUE else args[1:]
    if name == 'git' and args:
        sub, rest = args[0], args[1:]
        flagged = rest[:rest.index('--')] if '--' in rest else rest  # after `--` come names, not options
        short = [a for a in flagged if a[:1] == '-' and a[1:2] != '-']
        dry = '--dry-run' in flagged or any('n' in a for a in short)
        if sub == 'reset' and any(a in ('--hard', '--har', '--ha') for a in flagged): return 'git reset --hard throws away uncommitted work.'
        if sub == 'push' and not dry and ('--force' in flagged or any('f' in a for a in short) or any(a.startswith('+') for a in rest)):
            return 'Force push rewrites shared history; use --force-with-lease if you must.'
        if sub == 'clean' and not dry and ('--force' in flagged or any('f' in a for a in short)):
            return 'git clean -f deletes untracked files for good.'
    return ''


def _nested(inner, budget, depth):
    """Rules for a command string found inside powershell -Command or cmd /c: bash-style git/rm rules, PowerShell Remove-Item, cmd rd/del."""
    budget[0] -= 3 * len(inner)
    if budget[0] < 0: return _TOO_BIG
    return command_reason(inner, True, budget, depth + 1) or powershell_reason(inner, depth + 1) or cmd_reason(inner)


_TOO_BIG = 'The command is too long or nested too deeply for ws guards to check; ask the user to run it.'
_RAW = re.compile(r'"[^"]*"?|\'[^\']*\'?|\S+')
_EXE_TOKEN = re.compile(r'(?i)(?:.*[\\/])?(?:powershell|pwsh|cmd)(?:\.exe)?')
_PS_VALUE = ('executionpolicy', 'windowstyle', 'inputformat', 'outputformat', 'version', 'configurationname', 'workingdirectory', 'settingsfile', 'custompipename')


def _unquote(text):
    text = text.strip().replace('\\"', '"').replace('`"', '"')
    return text[1:].rstrip('"\'') if text[:1] in '"\'' else text


def _wrapped(cmd, name, args, budget):
    """Inner command strings of powershell/pwsh (-Command, -EncodedCommand and abbreviations, or a positional command) and cmd /c (or Git Bash //c),
    cut from the raw text so Windows paths keep their backslashes. At most 300 words are read, so the cost stays linear."""
    tail = cmd.src[cmd.start:]; budget[0] -= len(tail)
    toks = list(itertools.islice(_RAW.finditer(tail), 300))
    k = next((k for k, m in enumerate(toks) if _EXE_TOKEN.fullmatch(m[0].strip('"\''))), None)
    if k is None: yield ' '.join(args); return  # could not find the executable in the raw text: check what the words say
    toks = toks[k + 1:]
    if name == 'cmd':
        for m in toks:
            if re.fullmatch(r'(?i)//?[ck]', m[0]): yield _unquote(tail[m.end():]); return
        return
    i, positional = 0, None
    while i < len(toks):
        m = toks[i]; word = m[0].strip('"\''); i += 1
        flag = word[1:].lower().split(':')[0]
        if word[:1] != '-' or not flag:
            if positional is None: positional = m.start()
        elif flag == 'ec' or 'encodedcommand'.startswith(flag):
            if i < len(toks):
                try: yield base64.b64decode(toks[i][0].strip('"\''), validate=True).decode('utf-16-le')
                except ValueError: pass  # includes UnicodeDecodeError and binascii.Error
            return
        elif flag == 'c' or 'commandwithargs'.startswith(flag): yield _unquote(tail[m.end():]); return
        elif 'file'.startswith(flag): return
        elif flag == 'ep' or any(v.startswith(flag) for v in _PS_VALUE): i += 1
    if positional is not None: yield _unquote(tail[positional:])  # pwsh 'Remove-Item ...'


def command_reason(command, ps=False, _budget=None, _depth=0):
    budget = _budget if _budget is not None else [4 * len(command) + 50000]  # total text the nested passes may read: bounded work, and over it the answer is deny, never allow
    budget[0] -= len(command)
    if budget[0] < 0 or _depth > 20: return _TOO_BIG
    cwd_bad = False  # an earlier `cd ~` / `cd /` in this command: rm -rf * then wipes home or root
    for cmd in _scan(command, ps):
        words, xargs = _strip(cmd.words)
        if not words: continue
        name, args = _exe(words[0]), words[1:]
        if name in ('cd', 'pushd'):
            target = args[0] if args and args[0][:1] != '-' else '~' if not args else ''
            cwd_bad = bool(target) and (target in HOME_OR_ROOT or _is_home(target) or _is_root(target))
            continue
        why = _simple(cmd, name, args, xargs, cwd_bad, budget, _depth)
        if why: return why
    if looks_secret(command): return 'The command contains what looks like a secret (token, key or password).'
    return ''


PS_REMOVE = {'remove-item', 'rm', 'ri', 'del', 'erase', 'rd', 'rmdir'}


def _ps_flag(arg, full):
    """True when arg is -Name or an abbreviation of it (PowerShell accepts unambiguous prefixes), e.g. -r, -fo, -Recurse:$true; -Force:$false is off."""
    name, _, value = arg[1:].partition(':')
    return arg[:1] == '-' and bool(name) and full.startswith(name.lower()) and value.lower() not in ('$false', 'false', '0')


def _ps_home_or_root(a):
    return not a.startswith('-') and (not a.strip('\\/') or _is_home(a) or _is_root(a))


PS_HOOK_WRITE = {'set-content', 'sc', 'add-content', 'ac', 'out-file', 'clear-content', 'clc', 'new-item', 'ni', 'rename-item', 'ren', 'rni', 'move-item', 'move', 'mi', 'mv', 'tee-object', 'tee'} | PS_REMOVE
PS_HOOK_COPY = {'copy-item', 'copy', 'cp', 'cpi'}


def _ps_edits_hooks(words):
    """A PowerShell writer, mover, remover or redirect aimed at a hook config file (a copy only when the file is the destination)."""
    name, args = words[0].lower(), words[1:]
    if any(_HOOK_FILE.search(t) for t in _redirect_targets(words)): return True
    if name in PS_HOOK_WRITE: return any(_hook_arg(a) for a in args)
    if name in PS_HOOK_COPY:
        flag = lambda a: a[:1] == '-' and len(a) > 1 and 'destination'.startswith(a[1:].partition(':')[0].lower())  # -Destination, -Dest, -D:value
        named = [a.partition(':')[2] for a in args if flag(a) and ':' in a] + [args[k + 1] for k, a in enumerate(args[:-1]) if flag(a) and ':' not in a]
        operands = _operands(args)
        return any(_hook_arg(a) for a in named) or not named and bool(operands) and _hook_arg(operands[-1])
    return False


def powershell_reason(command, _depth=0):
    """Remove-Item (and aliases) -Recurse -Force on home or a drive root, also when piped in; skipped with -WhatIf; iex strings are checked too. Git and secrets go through command_reason."""
    for cmd in _scan(command, True):
        words = cmd.words
        if words[0].lower() in ('iex', 'invoke-expression') and _depth < 20:
            why = _nested(' '.join(words[1:]), [4 * len(command) + 50000], _depth)
            if why: return why
        if _ps_edits_hooks(words): return f'This would change the hook config that runs the guards. {_NO_DISABLE}'
        if words[0].lower() not in PS_REMOVE: continue
        args = words[1:]
        if not (any(_ps_flag(a, 'recurse') for a in args) and any(_ps_flag(a, 'force') for a in args)) or any(_ps_flag(a, 'whatif') for a in args): continue
        args += [a.partition(':')[2] for a in args if ':' in a and a[:1] == '-' and a.partition(':')[0][1:].lower() in ('p', 'pa', 'pat', 'path', 'l', 'li', 'lit', 'literalpath')]  # -Path:~
        pipe = cmd.pipe_in or []
        piped = [] if any(not a.startswith('-') for a in args) else pipe[1:] if len(pipe) > 1 else pipe
        for a in args + piped:
            if _ps_home_or_root(a):
                return f'Remove-Item -Recurse -Force on {a} would delete your home folder or a drive root.'
    return ''


CMD_REMOVE = {'rd', 'rmdir', 'del', 'erase'}


def cmd_reason(command):
    """cmd.exe rd/rmdir/del /s on home or a drive root (%USERPROFILE%, C:\\, %SystemDrive%\\)."""
    for cmd in _scan(command, True):
        words = cmd.words
        while words and words[0].lower() in ('call', '@'): words = words[1:]
        if not words or words[0].lower().lstrip('@') not in CMD_REMOVE: continue
        args = words[1:]
        if not any(a.lower() == '/s' for a in args): continue
        for a in args:
            if not re.fullmatch(r'/[a-z?]', a, re.I) and (_ps_home_or_root(a) or a.lower().rstrip('\\/') == '%systemdrive%'):
                return f'{words[0]} /s on {a} would delete your home folder or a drive root.'
    return ''


def _added(tool_input, cwd):
    """(new text, removed text) a file edit would introduce, for Claude Write/Edit/MultiEdit/NotebookEdit and Codex apply_patch."""
    if 'edits' in tool_input and isinstance(tool_input['edits'], list):
        pairs = [(e.get('new_string', ''), e.get('old_string', '')) for e in tool_input['edits'] if isinstance(e, dict)]
        return ''.join(p[0] for p in pairs), ''.join(p[1] for p in pairs)
    if 'new_string' in tool_input: return str(tool_input['new_string']), str(tool_input.get('old_string', ''))
    if 'new_source' in tool_input: return str(tool_input['new_source']), ''
    if 'content' in tool_input:
        old = ''
        try: old = (Path(cwd or '.') / str(tool_input.get('file_path', ''))).read_text(encoding='utf-8', errors='replace')
        except OSError: pass
        return str(tool_input['content']), old
    return '', ''


def _fragment_reason(new, old):
    """Hook-config edit seen only as text (the file cannot be read): fewer guard words or a new WS_GUARDS switch."""
    if _guard_marks(new) < _guard_marks(old) or 'WS_GUARDS' in new and 'WS_GUARDS' not in old:
        return f'This edit would switch the ws guards hook off. {_NO_DISABLE}'
    return ''


def _is_guard_command(command):
    """A ws guard hook command: `<python> <kit>/bin/ws ... guard --hook ...`, plain or in the encoded Windows launcher."""
    try:
        parts = shlex.split(command, posix=not core.WINDOWS)
        if core.WINDOWS: parts = [_unquote(word) for word in parts]
        if parts[:1] == [core._HOOK_PREFIX[0]]: parts = core.encoded_hook_args(parts)
    except ValueError: return False
    return 'guard' in parts and '--hook' in parts and any(_exe(w) in ('ws', 'ws-plugin') for w in parts)


def _guard_entries(text):
    """{command: tools its matcher covers} of the ws guard PreToolUse hooks in a hook-config text; None when the text is not a JSON object."""
    try: data = core.json_loads(text)
    except ValueError: return None
    if not isinstance(data, dict): return None
    groups = data['hooks'].get('PreToolUse') if isinstance(data.get('hooks'), dict) and data['hooks'].get('enabled') is not False else None
    found = {}
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict) or not isinstance(group.get('hooks'), list): continue
        matcher = group.get('matcher')
        for entry in group['hooks']:
            command = entry.get('command') if isinstance(entry, dict) else None
            if not isinstance(command, str) or not _is_guard_command(command) or entry.get('type', 'command') != 'command': continue
            covered = set()
            for tool in _GUARD_TOOLS:
                try: covered.add(tool) if matcher in (None, '', '*') or isinstance(matcher, str) and re.fullmatch(matcher, tool) else None
                except re.error: pass
            found[command] = found.get(command, set()) | covered
    return found


def _config_reason(before, after):
    """Deny when a ws guard hook that `before` has is gone, rewritten or no longer matches a tool it guarded in `after`, or hooks get switched off."""
    old, new = _guard_entries(before) or {}, _guard_entries(after)
    off = f'This edit would switch the ws guards hook off. {_NO_DISABLE}'
    if 'WS_GUARDS' in after and 'WS_GUARDS' not in before: return off
    if new is None: return off if old else ''  # not valid JSON any more: the client ignores the whole file
    if any(command not in new or not covered <= new[command] for command, covered in old.items()): return off
    try: disabled = lambda text: bool(core.json_loads(text).get('disableAllHooks'))
    except (ValueError, AttributeError): return ''
    return off if disabled(after) and not disabled(before) else ''


def _read(path, cwd):
    try: return (Path(cwd or '.') / os.path.expanduser(path)).read_text(encoding='utf-8')
    except (OSError, ValueError): return None


def _after_edit(tool_input, before):
    """Text of the file once a Claude Edit / MultiEdit / Write is applied to `before`; None when an edit does not apply (the tool itself will refuse it)."""
    if 'content' in tool_input: return str(tool_input['content'])
    edits = tool_input['edits'] if isinstance(tool_input.get('edits'), list) else [tool_input]
    text = before
    for edit in edits:
        if not isinstance(edit, dict) or 'new_string' not in edit: continue
        old = str(edit.get('old_string', ''))
        if not old or old not in text: return None
        text = text.replace(old, str(edit['new_string']), -1 if edit.get('replace_all') else 1)
    return text


def _hook_edit_reason(tool_input, path, cwd):
    before = _read(path, cwd)
    if before is None:
        new, old = _added(tool_input, cwd)
        return _fragment_reason(new, old)
    after = _after_edit(tool_input, before)
    return '' if after is None else _config_reason(before, after)


def _edit_reason(new, old):
    if len(MUTED.findall(new)) > len(MUTED.findall(old)): return 'This edit skips or narrows tests (skip/only); fix the test or ask the user first.'
    if secret_values(new) - secret_values(old): return 'This edit writes what looks like a secret (token, key or password) into a file.'
    return ''


_PATCH_FILE = re.compile(r'(?m)^\*\*\* (Update|Add|Delete) File: (.+?)\s*$')


def _apply_hunks(text, lines):
    """Text after the hunks of one `*** Update File` section (' ' context, '-' removed, '+' added lines), or None when a hunk does not match."""
    hunks, cur = [], None
    for line in lines:
        if line.startswith('@@'): cur = None; continue
        if line.startswith('***'): continue
        if cur is None: cur = []; hunks.append(cur)
        cur.append(line if line[:1] in (' ', '-', '+') else ' ' + line)
    pos = 0
    for hunk in hunks:
        old = '\n'.join(l[1:] for l in hunk if l[0] != '+'); new = '\n'.join(l[1:] for l in hunk if l[0] != '-')
        at = text.find(old, pos)
        if at < 0: return None
        text = text[:at] + new + text[at + len(old):]; pos = at + len(new)
    return text


def _patch_reason(patch, cwd=None):
    """Each file of an apply_patch is judged on its own lines, so a hook removal or a new skip/secret in one file is never masked by text in another."""
    marks = list(_PATCH_FILE.finditer(patch))
    if not marks: return _edit_reason('\n'.join(l[1:] for l in patch.splitlines() if l.startswith('+')), '\n'.join(l[1:] for l in patch.splitlines() if l.startswith('-')))
    for k, mark in enumerate(marks):
        kind, path = mark[1], mark[2]
        lines = patch[mark.end():marks[k + 1].start() if k + 1 < len(marks) else len(patch)].splitlines()
        move = next((l[len('*** Move to: '):].strip() for l in lines if l.startswith('*** Move to: ')), '')
        body = [l for l in lines if l.strip() and not l.startswith('*** ')] if kind != 'Update' else lines
        new = '\n'.join(l[1:] for l in body if l.startswith('+')); old = '\n'.join(l[1:] for l in body if l.startswith('-'))
        target = move or path
        if kind == 'Delete' and _HOOK_FILE.search(path) or move and _HOOK_FILE.search(path) and not _HOOK_FILE.search(move):
            return f'This patch deletes the hook config that runs the guards. {_NO_DISABLE}'
        if _HOOK_FILE.search(target):
            before = _read(target, cwd)
            source = before if kind != 'Update' or not move else _read(path, cwd)
            if kind == 'Add': after = new
            elif source is None: after = None
            else: after = _apply_hunks(source, lines)
            why = _fragment_reason(new, old) if before is None or after is None else _config_reason(before, after)
            if why: return why
        why = _edit_reason(new, old)
        if why: return why
    return ''


def _command_text(tool_name, tool_input):
    """The shell command or patch text of a tool call: Claude `command`, Codex `command` (argv list) or `cmd`, a patch in `input`."""
    for key in ('command', 'cmd', 'input'):
        value = tool_input.get(key)
        if isinstance(value, list): value = shlex.join(map(str, value))  # Codex sends argv, e.g. ["bash", "-lc", "..."]
        if isinstance(value, str) and value and (key != 'input' or tool_name == 'apply_patch' or value.lstrip().startswith('*** Begin Patch')): return value
    return ''


def reason(tool_name, tool_input, cwd=None):
    if os.environ.get('WS_GUARDS', '').lower() in ('off', '0', 'false'): return ''
    if not isinstance(tool_input, dict): return ''
    command = _command_text(tool_name, tool_input)
    if tool_name == 'apply_patch' or command.lstrip().startswith('*** Begin Patch'): return _patch_reason(command, cwd)
    if command: return command_reason(command, tool_name == 'PowerShell') or powershell_reason(command)  # PowerShell rules for every tool: Codex on Windows runs PowerShell under a Bash-named tool
    path = str(tool_input.get('file_path') or tool_input.get('notebook_path') or '')
    why = _hook_edit_reason(tool_input, path, cwd) if _HOOK_FILE.search(path) else ''
    return why or _edit_reason(*_added(tool_input, cwd))


def hook(payload, client='claude'):
    """PreToolUse output in the selected client dialect; unknown inputs fail open."""
    allow = {'permission': 'allow'} if client == 'cursor' else {}  # Cursor blocks a permission hook whose output it cannot read
    if not isinstance(payload, dict): return allow
    if client == 'antigravity':
        call = payload.get('toolCall'); call = call if isinstance(call, dict) else {}
        args = call.get('args'); args = args if isinstance(args, dict) else {}
        paths = payload.get('workspacePaths')
        mapped = dict(args)
        for native, common in (('CommandLine', 'command'), ('Path', 'file_path'),
                               ('Content', 'content'), ('Target', 'old_string'), ('Replacement', 'new_string'),
                               ('TargetFile', 'file_path'),
                               ('CodeContent', 'content'), ('TargetContent', 'old_string'),
                               ('ReplacementContent', 'new_string')):
            if native in args: mapped[common] = args[native]
        if isinstance(args.get('ReplacementChunks'), list):
            mapped['edits'] = [{'old_string': chunk.get('TargetContent', ''), 'new_string': chunk.get('ReplacementContent', '')}
                               for chunk in args['ReplacementChunks'] if isinstance(chunk, dict)]
        payload = {'tool_name': call.get('name'), 'tool_input': mapped,
                   'cwd': paths[0] if isinstance(paths, list) and paths else None}
    why = reason(payload.get('tool_name', ''), payload.get('tool_input'), payload.get('cwd'))
    if not why: return {'decision': 'allow'} if client == 'antigravity' else allow
    why = f'ws guards: {why} If the user really wants this, they can run it themselves or start the assistant with WS_GUARDS=off.'
    if client == 'cursor': return {'permission': 'deny', 'user_message': why, 'agent_message': why}
    if client == 'antigravity': return {'decision': 'deny', 'reason': why}
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': why}}
