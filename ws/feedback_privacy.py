"""Extra issue-bound filtering, never applied to local notes or generic redact."""
import re

from . import core

_TOKEN = re.compile(r'(?<!\w)(?:(?:lin_api_|ntn_|secret_)[A-Za-z0-9_-]{40,}|(?:ya29\.|pypi-)[A-Za-z0-9._-]{20,})')
_CARD = re.compile(r'(?<![\w.])(?=((?:[0-9][ -]*){12,18}[0-9](?!\w)(?!\.[0-9])))')
_IBAN = re.compile(r'(?<!\w)[A-Za-z]{2}[0-9]{2}')
_ACCOUNT = re.compile(r'(?<![\w.+-])[0-9]{9,18}(?!\w)(?![.-]\w)')
_URL = re.compile(r'\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>]+')


def _luhn(value):
    digits = [int(c) for c in value if c.isdigit()]
    return sum((d * 2 - 9 if d > 4 else d * 2) if i % 2 else d
               for i, d in enumerate(reversed(digits))) % 10 == 0


def _cards(text):
    parts, cursor = [], 0
    for match in _CARD.finditer(text):
        if match.start() < cursor:
            continue
        value = match[1]
        # A neighboring number can look like an extra group. Try shorter
        # candidates at separators, and let the scan try later group starts.
        while sum(c.isdigit() for c in value) >= 13:
            if _luhn(value):
                parts.extend((text[cursor:match.start()], '[REDACTED]'))
                cursor = match.start() + len(value)
                break
            end = max(value.rfind(' '), value.rfind('-'))
            if end < 0:
                break
            value = value[:end].rstrip(' -')
    return ''.join(parts) + text[cursor:]


def _mod97(value):
    remainder = 0
    for char in value[4:] + value[:4]:
        remainder = (remainder * (10 if char.isdigit() else 100) +
                     (int(char) if char.isdigit() else ord(char) - 55)) % 97
    return remainder == 1


def _ibans(text):
    parts, cursor = [], 0
    for match in _IBAN.finditer(text):
        if match.start() < cursor: continue
        value, end, pos = '', None, match.start()
        # At most 34 alphanumeric characters; spaces do not count toward IBAN length.
        while pos < len(text) and len(value) < 34:
            char = text[pos]
            if char == ' ': pos += 1; continue
            if not (char.isascii() and char.isalnum()): break
            value += char.upper()
            pos += 1
            if len(value) >= 15 and (pos == len(text) or not text[pos].isalnum()) and _mod97(value):
                end = pos
        if end is not None:
            parts.extend((text[cursor:match.start()], '[REDACTED]'))
            cursor = end
    return ''.join(parts) + text[cursor:]


def issue_text(text):
    """Redact before title truncation and before either external submission route.

    Token heuristics require 40 suffix characters for Linear/Notion, 20 for
    Google/PyPI. Checksums do not prove an identifier is real; preview is required.
    """
    text = _TOKEN.sub('[REDACTED]', core.redact(text))
    text = _ibans(text)
    text = _cards(text)
    # Account heuristics must not remove numeric URL paths; query values still count.
    parts, cursor = [], 0
    for match in _URL.finditer(text):
        parts.append(_ACCOUNT.sub('[REDACTED]', text[cursor:match.start()]))
        url = match[0]
        boundary = min([url.find(c) for c in ('?', '#') if c in url] or [len(url)])
        path = url.find('/', url.index('://') + 3)
        if 0 <= path < boundary:
            parts.extend((_ACCOUNT.sub('[REDACTED]', url[:path]), url[path:boundary],
                          _ACCOUNT.sub('[REDACTED]', url[boundary:])))
        else:
            parts.append(_ACCOUNT.sub('[REDACTED]', url))
        cursor = match.end()
    return ''.join(parts) + _ACCOUNT.sub('[REDACTED]', text[cursor:])
